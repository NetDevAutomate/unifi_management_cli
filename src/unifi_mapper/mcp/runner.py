"""One request pipeline for every catalog tool call (design §2.5).

``ToolRunner.run`` serves both ``execute_tool`` and the opt-in direct surface:

1. lookup, 2. mutation gate, 3. lazy catalog build, 4. alias rewrite,
5. unknown-key check, 6. argument validation against the handler signature,
7. credential gate by the tool's family, 8. execution under a concurrency cap (and a
deadline only when ``UNIFI_MCP_TOOL_TIMEOUT`` is set), 9. error mapping to stable codes,
10. masking of every result and error text, 11. the result for the surface.

The runner never raises: every outcome is a ``CallToolResult``. On ``execute_tool``
its single text block is exactly today's JSON envelope and ``structuredContent`` is the
same dict; failures set ``isError`` (``ERRORS_SET_IS_ERROR``).
"""

import anyio
import asyncio
import inspect
import os
import pydantic_core
from .catalog import ToolCatalog, ToolNotLoadableError
from .config import (
    FOREIGN_FILE_SUGGESTION,
    CredentialsMissingError,
    ResolvedConfig,
    ServerSettings,
    ensure_controller_credentials,
    family_status,
)
from .registry import InvalidParamsError, MutationRefusedError, ToolRegistry, UnknownToolError
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from loguru import logger
from mcp.server.fastmcp.tools import Tool
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ValidationError
from typing import Any, Literal
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.readonly import ReadOnlyViolation
from unifi_mapper.core.utils.redact import mask_secret_values, mask_secrets, mcp_secret_values


Surface = Literal['execute_tool', 'direct']

TOOL_FAILED_TEXT_LIMIT = 500
ERROR_TEXT_LIMIT = 2000
# Plan decision P1 (design D1): failures carry isError: true. One constant to revert.
ERRORS_SET_IS_ERROR = True

TOOL_FAILED = 'TOOL_FAILED'
TOOL_NOT_FOUND = 'TOOL_NOT_FOUND'
MUTATION_REFUSED = 'MUTATION_REFUSED'
INVALID_PARAMETERS = 'INVALID_PARAMETERS'

TOOL_NOT_FOUND_SUGGESTION = 'Use search_tools or list_categories to find the right name.'
MUTATION_REFUSED_SUGGESTION = (
    'Generate a plan with the read-only tools, review it, then apply it with the unifi-mapper CLI.'
)
INVALID_PARAMETERS_SUGGESTION = 'Check get_tool_info for the parameter list.'
TOOL_FAILED_SUGGESTION = 'Run the equivalent unifi-mapper CLI command for a full traceback.'
READ_ONLY_SUGGESTION = 'This is a bug in the tool; nothing was written. Report it.'
TIMEOUT_SUGGESTION = 'Narrow the request, or raise UNIFI_MCP_TOOL_TIMEOUT.'

# Per-tool hints for unknown parameters: (tool, parameter) -> hint.
UNKNOWN_PARAMETER_HINTS: dict[tuple[str, str], str] = {}

_FAMILY_SUGGESTIONS = {
    'network_api': (
        'set UNIFI_CONFIG to an env file with UNIFI_NETWORK_HOST, UNIFI_NETWORK_API_KEY '
        'and UNIFI_NETWORK_SITE_ID, or export them'
    ),
    'protect': (
        'set UNIFI_CONFIG to an env file with PROTECT_HOST, PROTECT_USERNAME and '
        'PROTECT_PASSWORD, or export them'
    ),
}


class ExecuteResult(BaseModel):
    """``execute_tool``'s output schema. Never used to build envelopes."""

    ok: bool
    result: Any = None
    error_code: str | None = None
    message: str | None = None
    suggestion: str | None = None
    related_tools: list[str] | None = None
    parameters: dict[str, Any] | None = None
    input_schema: dict[str, Any] | None = None


def _to_jsonable(value: Any) -> Any:
    """Convert tool results (pydantic models, dataclasses, nested) to JSON-safe data."""
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    return value


def success_envelope(masked: Any) -> dict[str, Any]:
    """Return today's success dict; 'result' is kept even when it is None."""
    return {'ok': True, 'result': masked}


def error_envelope(
    error_code: str,
    message: str,
    suggestion: str,
    *,
    related_tools: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
    input_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return today's failure dict: required keys always, optional error keys if not None."""
    optional = {
        'related_tools': related_tools,
        'parameters': parameters,
        'input_schema': input_schema,
    }
    return {
        'ok': False,
        'error_code': error_code,
        'message': message,
        'suggestion': suggestion,
        **{key: value for key, value in optional.items() if value is not None},
    }


def envelope_text(envelope: dict[str, Any]) -> str:
    """Serialise an envelope exactly as FastMCP serialised ``execute_tool``'s dict."""
    return pydantic_core.to_json(envelope, fallback=str, indent=2).decode()


def exception_text(e: BaseException) -> str:
    """Return an exception's text; a ValidationError is rendered without input values.

    Args:
        e: The exception.

    Returns:
        ``str(e)``, or ``loc (msg)`` parts for a pydantic ``ValidationError``.
    """
    if isinstance(e, ValidationError):
        parts = [
            f'{".".join(str(p) for p in err.get("loc", ())) or "value"} ({err.get("msg", "")})'
            for err in e.errors(include_input=False, include_url=False)
        ]
        return f'{e.error_count()} validation error(s) for {e.title}: {"; ".join(parts)}'
    return str(e)


@dataclass(eq=False)
class _Failure(Exception):
    """An error outcome, with its text not yet masked."""

    error_code: str
    message: str
    suggestion: str
    related_tools: list[str] | None = None
    parameters: dict[str, Any] | None = None
    input_schema: dict[str, Any] | None = None
    # Kept out of masking so a class name is never matched as a secret name (NIT 3).
    message_prefix: str = ''

    @classmethod
    def from_tool_error(cls, e: ToolError) -> '_Failure':
        """Map a domain ToolError through ``to_dict()`` (empty values kept, as today)."""
        d = e.to_dict()
        return cls(
            error_code=str(d['error_code']),
            message=str(d['message']),
            suggestion=str(d['suggestion']),
            related_tools=list(e.related_tools),
        )

    @classmethod
    def tool_failed(cls, e: BaseException) -> '_Failure':
        """Map any other exception to TOOL_FAILED in today's ``Class: text`` format."""
        return cls(
            error_code=TOOL_FAILED,
            message=exception_text(e),
            suggestion=TOOL_FAILED_SUGGESTION,
            message_prefix=f'{type(e).__name__}: ',
        )

    def masked(self, secrets: frozenset[str]) -> '_Failure':
        """Return a copy whose message and suggestion are masked and capped."""
        limit = TOOL_FAILED_TEXT_LIMIT if self.error_code == TOOL_FAILED else ERROR_TEXT_LIMIT
        body_limit = max(limit - len(self.message_prefix), 1)
        return _Failure(
            error_code=self.error_code,
            message=self.message_prefix
            + mask_secret_values(self.message, secrets, limit=body_limit),
            suggestion=mask_secret_values(self.suggestion, secrets, limit=ERROR_TEXT_LIMIT),
            related_tools=self.related_tools,
            parameters=self.parameters,
            input_schema=self.input_schema,
        )


class ToolRunner:
    """Validate, gate, run, mask and package one catalog tool call."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        settings: ServerSettings | None = None,
        config: Callable[[], ResolvedConfig | None] | None = None,
        catalog: ToolCatalog | None = None,
    ) -> None:
        """Create a runner for ``registry``.

        Args:
            registry: The manifest registry.
            settings: Concurrency cap, credential timeout and optional tool deadline.
            config: Returns the resolved MCP config (for the paths tried), if any.
            catalog: The SDK tool catalog; built from ``registry`` when omitted.
        """
        self.registry = registry
        self.catalog = catalog or ToolCatalog(registry)
        self.settings = settings or ServerSettings()
        self._config = config or (lambda: None)
        self._semaphore: anyio.Semaphore | None = None
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None

    def is_direct(self, name: str) -> bool:
        """Return True if ``name`` is a catalog tool listed on the direct surface."""
        return self.catalog.is_direct(name)

    def _limit(self) -> anyio.Semaphore:
        """Return the concurrency semaphore for the running event loop."""
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not loop:
            self._semaphore = anyio.Semaphore(self.settings.max_concurrency)
            self._semaphore_loop = loop
        return self._semaphore

    async def run(
        self, name: str, params: dict[str, Any] | None, surface: Surface = 'execute_tool'
    ) -> CallToolResult:
        """Run catalog tool ``name`` with ``params`` and package the outcome.

        Args:
            name: The tool name.
            params: Raw arguments (``None`` means none).
            surface: ``'execute_tool'`` (today's envelope) or ``'direct'``.

        Returns:
            The call result; never raises.
        """
        try:
            tool, kwargs = await self._prepare(name, dict(params or {}))
            result = await self._execute(name, tool, kwargs)
            secrets = mcp_secret_values(os.environ)
            return self._success(tool, result, secrets, surface)
        except _Failure as failure:
            return self._failure(failure, mcp_secret_values(os.environ), surface)
        except Exception as e:  # noqa: BLE001 - the runner never raises out of a tool call
            logger.exception('MCP tool {} failed while packaging its result', name)
            return self._failure(_Failure.tool_failed(e), mcp_secret_values(os.environ), surface)

    # --- steps 1-7 --------------------------------------------------------------------

    async def _prepare(self, name: str, params: dict[str, Any]) -> tuple[Tool, dict[str, Any]]:
        """Look up, refuse mutation, build, rewrite aliases, validate and gate."""
        meta = self.registry.get_metadata(name)
        try:
            tool = self.catalog.get(name)
        except UnknownToolError:
            raise _Failure(
                TOOL_NOT_FOUND, f'No tool named {name!r}', TOOL_NOT_FOUND_SUGGESTION
            ) from None
        except MutationRefusedError:
            raise _Failure(
                MUTATION_REFUSED,
                f'{name} changes live controller configuration and is not executable over MCP.',
                MUTATION_REFUSED_SUGGESTION,
            ) from None
        except ToolNotLoadableError as e:
            raise _Failure(
                TOOL_FAILED, f'tool not loadable: {e.exc_type}', TOOL_FAILED_SUGGESTION
            ) from None
        assert meta is not None  # the catalog found it

        try:
            kwargs = self._validate(name, tool, self._rewrite_aliases(meta.aliases, params))
        except InvalidParamsError as e:
            raise _Failure(
                INVALID_PARAMETERS,
                str(e),
                INVALID_PARAMETERS_SUGGESTION,
                parameters=meta.parameters,
                input_schema=e.input_schema or tool.parameters,
            ) from None

        await self._gate(meta.credentials)
        return tool, kwargs

    @staticmethod
    def _rewrite_aliases(aliases: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
        """Rename deprecated parameter names to their canonical names (step 4)."""
        for alias, canonical in aliases.items():
            if alias not in params:
                continue
            if canonical in params:
                raise InvalidParamsError(
                    f'both {canonical} and its deprecated alias {alias} were given; '
                    f'pass only {canonical}'
                )
            params = {(canonical if k == alias else k): v for k, v in params.items()}
        return params

    @staticmethod
    def _validate(name: str, tool: Tool, params: dict[str, Any]) -> dict[str, Any]:
        """Reject unknown keys, then validate against the handler signature (steps 5-6)."""
        known = set(tool.parameters.get('properties', {}))
        unknown = sorted(set(params) - known)
        if unknown:
            message = f'unknown parameter(s): {", ".join(unknown)}'
            hints = [
                UNKNOWN_PARAMETER_HINTS[(name, p)]
                for p in unknown
                if (name, p) in UNKNOWN_PARAMETER_HINTS
            ]
            if hints:
                message = f'{message}. {"; ".join(hints)}'
            raise InvalidParamsError(message, input_schema=tool.parameters)
        meta_fn = tool.fn_metadata
        try:
            parsed = meta_fn.arg_model.model_validate(meta_fn.pre_parse_json(params))
        except ValidationError as e:
            raise InvalidParamsError.from_errors(
                list(e.errors(include_input=False, include_url=False)),
                input_schema=tool.parameters,
            ) from e
        return parsed.model_dump_one_level()

    async def _gate(self, family: str) -> None:
        """Check the tool's credential family is ready (step 7)."""
        if family == 'none':
            return
        config = self._config()
        tried = config.tried if config is not None else ()
        try:
            if family == 'controller':
                await ensure_controller_credentials(self.settings.credential_timeout, tried)
                return
            status = family_status(family, os.environ, 'environment')
            if status.ready:
                return
            message = f'missing {", ".join(status.missing)}'
            suggestion = _FAMILY_SUGGESTIONS.get(family, '')
            if config is not None:
                skipped = config.families.get(family)
                if skipped is not None and skipped.skipped_reason:
                    where = config.path or 'the config file'
                    message = f'{message}; {where} was not applied: {skipped.skipped_reason}'
                    suggestion = FOREIGN_FILE_SUGGESTION
            raise CredentialsMissingError(message, suggestion=suggestion, tried=tried)
        except ToolError as e:
            raise _Failure.from_tool_error(e) from None
        except Exception as e:  # noqa: BLE001 - a broken credential chain is a tool failure
            logger.exception('credential check failed')
            raise _Failure.tool_failed(e) from None

    # --- steps 8-9 --------------------------------------------------------------------

    async def _execute(self, name: str, tool: Tool, kwargs: dict[str, Any]) -> Any:
        """Run the handler under the concurrency cap and the optional deadline."""
        timeout = self.settings.tool_timeout
        scope: anyio.CancelScope | None = None
        try:
            async with self._limit():
                if timeout is None:
                    return await self._call(tool, kwargs)
                with anyio.fail_after(timeout) as scope:
                    return await self._call(tool, kwargs)
        except CredentialsMissingError as e:
            raise _Failure.from_tool_error(e) from None
        except ToolError as e:
            logger.info('MCP tool {} returned {}', name, e.error_code)
            raise _Failure.from_tool_error(e) from None
        except ReadOnlyViolation as e:
            raise _Failure(
                ErrorCodes.READ_ONLY_VIOLATION,
                f'A controller write was refused by the read-only guard: {e}',
                READ_ONLY_SUGGESTION,
            ) from None
        except TimeoutError as e:
            if scope is not None and scope.cancelled_caught:
                logger.warning('MCP tool {} exceeded {}s', name, timeout)
                raise _Failure(
                    ErrorCodes.TIMEOUT,
                    f'{name} did not finish within {timeout:g}s (UNIFI_MCP_TOOL_TIMEOUT)',
                    TIMEOUT_SUGGESTION,
                ) from None
            logger.exception('MCP tool {} failed', name)
            raise _Failure.tool_failed(e) from None
        except Exception as e:  # noqa: BLE001 - surface any tool failure, don't crash the server
            logger.exception('MCP tool {} failed', name)
            raise _Failure.tool_failed(e) from None

    @staticmethod
    async def _call(tool: Tool, kwargs: dict[str, Any]) -> Any:
        """Call the handler: awaited if async, else called directly (today's behaviour)."""
        if tool.is_async:
            return await tool.fn(**kwargs)
        result = tool.fn(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    # --- steps 10-11 ------------------------------------------------------------------

    @staticmethod
    def _success(
        tool: Tool, result: Any, secrets: frozenset[str], surface: Surface
    ) -> CallToolResult:
        """Mask the result, then build the surface's success result."""
        if surface == 'execute_tool':
            envelope = success_envelope(mask_secrets(_to_jsonable(result), secrets))
            return CallToolResult(
                content=[TextContent(type='text', text=envelope_text(envelope))],
                structuredContent=envelope,
                isError=False,
            )
        masked = mask_secrets(
            pydantic_core.to_jsonable_python(result, by_alias=True, fallback=str), secrets
        )
        converted = tool.fn_metadata.convert_result(masked)
        if isinstance(converted, tuple):
            content, structured = converted
        else:
            content, structured = converted, None
        return CallToolResult(content=list(content), structuredContent=structured, isError=False)

    @staticmethod
    def _failure(failure: _Failure, secrets: frozenset[str], surface: Surface) -> CallToolResult:
        """Mask the error text, then build the surface's failure result."""
        f = failure.masked(secrets)
        if surface == 'execute_tool':
            envelope = error_envelope(
                f.error_code,
                f.message,
                f.suggestion,
                related_tools=f.related_tools,
                parameters=f.parameters,
                input_schema=f.input_schema,
            )
            return CallToolResult(
                content=[TextContent(type='text', text=envelope_text(envelope))],
                structuredContent=envelope,
                isError=ERRORS_SET_IS_ERROR,
            )
        text = f'[{f.error_code}] {f.message}'
        if f.suggestion:
            text = f'{text} — {f.suggestion}'
        return CallToolResult(content=[TextContent(type='text', text=text)], isError=True)
