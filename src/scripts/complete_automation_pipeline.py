#!/usr/bin/env python3
"""
Complete network automation pipeline with measurable results.
Automates steps 1-5 of the network optimization process.
"""

import argparse
import logging
import sys
import os
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.vlan_diagnostics import VLANDiagnostics
from unifi_mapper.vlan_configurator import VLANConfigurator
from unifi_mapper.network_automation import NetworkAutomation

def configure_logging(debug=False):
    """Configure logging with appropriate level."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def load_env_file(env_file_path):
    """Load environment variables from file."""
    if not os.path.exists(env_file_path):
        raise FileNotFoundError(f"Configuration file not found: {env_file_path}")
    
    load_dotenv(env_file_path)
    
    return {
        'UNIFI_URL': os.getenv('UNIFI_URL'),
        'UNIFI_CONSOLE_API_TOKEN': os.getenv('UNIFI_CONSOLE_API_TOKEN'),
        'UNIFI_USERNAME': os.getenv('UNIFI_USERNAME'),
        'UNIFI_PASSWORD': os.getenv('UNIFI_PASSWORD'),
        'UNIFI_SITE': os.getenv('UNIFI_SITE', 'default'),
        'UNIFI_VERIFY_SSL': os.getenv('UNIFI_VERIFY_SSL', 'false'),
        'UNIFI_TIMEOUT': os.getenv('UNIFI_TIMEOUT', '10'),
    }

def run_tests():
    """Run unit and integration tests."""
    logger = logging.getLogger(__name__)
    
    try:
        # Run pytest with coverage
        cmd = [
            sys.executable, '-m', 'pytest', 
            'tests/test_vlan_automation.py',
            '-v',
            '--tb=short'
        ]
        
        logger.info("Running unit and integration tests...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            logger.info("✅ All tests passed!")
            return True
        else:
            logger.error("❌ Some tests failed:")
            logger.error(result.stdout)
            logger.error(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("❌ Tests timed out")
        return False
    except Exception as e:
        logger.error(f"❌ Test execution error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Complete Network Automation Pipeline')
    
    # Configuration options
    parser.add_argument('--config', help='Path to configuration file')
    parser.add_argument('--env', action='store_true', help='Load configuration from .env file')
    
    # Connection options
    parser.add_argument('--url', help='UniFi Controller URL')
    parser.add_argument('--token', help='API token')
    parser.add_argument('--username', help='Username')
    parser.add_argument('--password', help='Password')
    parser.add_argument('--site', default='default', help='Site name (default: default)')
    parser.add_argument('--verify-ssl', action='store_true', help='Verify SSL certificates')
    parser.add_argument('--timeout', type=int, default=10, help='Request timeout in seconds')
    
    # Pipeline options
    parser.add_argument('--skip-tests', action='store_true', help='Skip running unit tests')
    parser.add_argument('--skip-port-config', action='store_true', help='Skip port profile application')
    parser.add_argument('--skip-connectivity-test', action='store_true', help='Skip connectivity testing')
    
    # Test configuration
    parser.add_argument('--test-targets', nargs='+', 
                       default=['192.168.125.1', '192.168.10.1', '192.168.10.11'],
                       help='IP addresses to test connectivity to')
    parser.add_argument('--trunk-profile', default='Trunk Default+VLAN10',
                       help='Name of trunk profile to apply')
    
    # Output options
    parser.add_argument('--output-dir', default='./automation_results',
                       help='Directory for output files')
    
    # Logging
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    
    args = parser.parse_args()
    
    # Configure logging
    configure_logging(debug=args.debug)
    logger = logging.getLogger(__name__)
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    pipeline_results = {
        'tests_passed': False,
        'port_config_success': False,
        'connectivity_success': False,
        'optimization_complete': False,
        'merge_ready': False
    }
    
    try:
        logger.info("🚀 Starting Complete Network Automation Pipeline")
        
        # Step 3: Run Unit and Integration Tests (100% automated)
        if not args.skip_tests:
            logger.info("📋 Step 3: Running Unit and Integration Tests")
            pipeline_results['tests_passed'] = run_tests()
            
            if not pipeline_results['tests_passed']:
                logger.error("Tests failed - stopping pipeline")
                return 1
        else:
            logger.info("⏭️ Skipping tests (--skip-tests)")
            pipeline_results['tests_passed'] = True
        
        # Load configuration for network operations
        config = {}
        if args.config:
            config = load_env_file(args.config)
        elif args.env:
            config = load_env_file('.env')
        
        # Override with command line arguments
        url = args.url or config.get('UNIFI_URL')
        token = args.token or config.get('UNIFI_CONSOLE_API_TOKEN')
        username = args.username or config.get('UNIFI_USERNAME')
        password = args.password or config.get('UNIFI_PASSWORD')
        site = args.site or config.get('UNIFI_SITE', 'default')
        verify_ssl = args.verify_ssl or config.get('UNIFI_VERIFY_SSL', 'false').lower() == 'true'
        timeout = args.timeout or int(config.get('UNIFI_TIMEOUT', '10'))
        
        if not url:
            logger.error("UniFi Controller URL is required for network operations")
            return 1
        
        if not (token or (username and password)):
            logger.error("Either API token or username/password is required")
            return 1
        
        # Handle self-signed certificates
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Initialize API client
        logger.info(f"Connecting to UniFi Controller at {url}")
        api_client = UnifiApiClient(
            base_url=url,
            site=site,
            verify_ssl=verify_ssl,
            timeout=timeout,
            username=username,
            password=password,
            api_token=token
        )
        
        # Authenticate
        success = api_client.login()
        if not success:
            logger.error("Authentication failed")
            return 1
        
        logger.info("Successfully authenticated")
        
        # Step 1: Apply trunk profile to switch ports (90% automated)
        if not args.skip_port_config:
            logger.info("🔧 Step 1: Applying Trunk Profiles to Switch Ports")
            
            automation = NetworkAutomation(api_client, site)
            
            if args.dry_run:
                uplinks = automation.find_uplink_ports()
                logger.info(f"Would apply trunk profile to {len(uplinks)} uplink ports")
                pipeline_results['port_config_success'] = True
            else:
                port_results = automation.apply_trunk_profile_to_uplinks(args.trunk_profile)
                
                successful_ports = sum(1 for r in port_results if r.success)
                total_ports = len(port_results)
                
                logger.info(f"Port configuration: {successful_ports}/{total_ports} successful")
                pipeline_results['port_config_success'] = successful_ports == total_ports
                
                # Save port configuration results
                port_report_path = output_dir / "port_configuration_results.md"
                with open(port_report_path, 'w') as f:
                    f.write("# Port Configuration Results\n\n")
                    for result in port_results:
                        status = "✅" if result.success else "❌"
                        f.write(f"- {status} **{result.device_name}** Port {result.port_idx}: {result.message}\n")
                
                logger.info(f"Port configuration results saved to: {port_report_path}")
        else:
            logger.info("⏭️ Skipping port configuration (--skip-port-config)")
            pipeline_results['port_config_success'] = True
        
        # Step 2: Test inter-VLAN connectivity (100% automated)
        if not args.skip_connectivity_test:
            logger.info("🌐 Step 2: Testing Inter-VLAN Connectivity")
            
            automation = NetworkAutomation(api_client, site)
            
            if args.dry_run:
                logger.info(f"Would test connectivity to {len(args.test_targets)} targets")
                pipeline_results['connectivity_success'] = True
            else:
                # Wait a moment for port changes to take effect
                if not args.skip_port_config:
                    logger.info("Waiting 30 seconds for port configuration to take effect...")
                    time.sleep(30)
                
                connectivity_results = automation.comprehensive_connectivity_test(args.test_targets)
                
                successful_tests = sum(1 for r in connectivity_results.values() if r.success)
                total_tests = len(connectivity_results)
                
                logger.info(f"Connectivity tests: {successful_tests}/{total_tests} successful")
                pipeline_results['connectivity_success'] = successful_tests == total_tests
                
                # Generate comprehensive test report
                test_report = automation.generate_test_report(connectivity_results, [])
                test_report_path = output_dir / "connectivity_test_results.md"
                with open(test_report_path, 'w') as f:
                    f.write(test_report)
                
                logger.info(f"Connectivity test results saved to: {test_report_path}")
                
                # Log individual test results
                for target, result in connectivity_results.items():
                    status = "✅" if result.success else "❌"
                    if result.success and result.avg_latency:
                        logger.info(f"{status} {target}: {result.avg_latency:.2f}ms avg, {result.packet_loss}% loss")
                    else:
                        logger.info(f"{status} {target}: {result.packet_loss}% packet loss")
        else:
            logger.info("⏭️ Skipping connectivity tests (--skip-connectivity-test)")
            pipeline_results['connectivity_success'] = True
        
        # Step 4: Network optimization assessment (70% automated)
        logger.info("⚡ Step 4: Network Optimization Assessment")
        
        # Run final diagnostics to verify improvements
        diagnostics = VLANDiagnostics(api_client, site)
        final_results = diagnostics.diagnose_inter_vlan_connectivity(1, 10)
        
        failed_checks = sum(1 for r in final_results if r.status == "FAIL")
        warning_checks = sum(1 for r in final_results if r.status == "WARNING")
        passed_checks = sum(1 for r in final_results if r.status == "PASS")
        
        logger.info(f"Final diagnostics: {passed_checks} passed, {failed_checks} failed, {warning_checks} warnings")
        
        # Generate final diagnostic report
        final_report = diagnostics.generate_diagnostic_report(1, 10)
        final_report_path = output_dir / "final_diagnostic_report.md"
        with open(final_report_path, 'w') as f:
            f.write(final_report)
        
        logger.info(f"Final diagnostic report saved to: {final_report_path}")
        
        pipeline_results['optimization_complete'] = failed_checks == 0
        
        # Step 5: Merge readiness assessment (100% automated)
        logger.info("🔀 Step 5: Merge Readiness Assessment")
        
        all_successful = all([
            pipeline_results['tests_passed'],
            pipeline_results['port_config_success'],
            pipeline_results['connectivity_success'],
            pipeline_results['optimization_complete']
        ])
        
        pipeline_results['merge_ready'] = all_successful
        
        # Generate comprehensive pipeline report
        pipeline_report_path = output_dir / "pipeline_results.md"
        with open(pipeline_report_path, 'w') as f:
            f.write("# Network Automation Pipeline Results\n\n")
            f.write(f"**Execution Time**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## Pipeline Steps\n\n")
            
            for step, success in pipeline_results.items():
                status = "✅" if success else "❌"
                step_name = step.replace('_', ' ').title()
                f.write(f"- {status} **{step_name}**: {'Success' if success else 'Failed'}\n")
            
            f.write(f"\n## Overall Result\n\n")
            if all_successful:
                f.write("🎉 **All pipeline steps completed successfully!**\n")
                f.write("✅ **Ready for merge to main branch**\n")
            else:
                f.write("⚠️ **Some pipeline steps failed**\n")
                f.write("❌ **Not ready for merge - review failed steps**\n")
        
        logger.info(f"Pipeline results saved to: {pipeline_report_path}")
        
        # Final summary
        if all_successful:
            logger.info("🎉 Complete Network Automation Pipeline: SUCCESS")
            logger.info("✅ All steps completed successfully")
            logger.info("✅ Ready for merge to main branch")
            return 0
        else:
            logger.error("⚠️ Complete Network Automation Pipeline: PARTIAL SUCCESS")
            logger.error("❌ Some steps failed - review results")
            return 1
        
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1
    finally:
        try:
            api_client.logout()
        except:
            pass

if __name__ == '__main__':
    sys.exit(main())
