import os
import sys
import yaml
import logging
from typing import Dict, Tuple, List
from datetime import datetime
import pandas as pd
from github import Github

class RepositoryHealthChecker:
    def __init__(self, token: str, org_name: str, config_path: str = None):
        """
        Initialize the repository health checker with comprehensive error handling
        
        :param token: GitHub API token
        :param org_name: GitHub organization name
        :param config_path: Path to the health check configuration file
        """
        logging.basicConfig(level=logging.INFO, 
                             format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
        # Determine config path
        if config_path is None:
            # Search for config in .github directory
            potential_paths = [
                os.path.join('.github', 'repo_health_config.yml'),
                os.path.join('.github', 'repo_health_config.yaml'),
                'repo_health_config.yml',
                'repo_health_config.yaml'
            ]
            
            for path in potential_paths:
                if os.path.exists(path):
                    config_path = path
                    break
            
            if not config_path:
                self.logger.warning("No configuration file found. Using default settings.")
                config_path = os.path.join('.github', 'repo_health_config.yml')

        try:
            with open(config_path, mode='r', encoding="utf-8") as config_file:
                self.config = yaml.safe_load(config_file)
            self.logger.info(f"Loaded configuration from {config_path}")
        except FileNotFoundError:
            self.logger.warning(f"Config file {config_path} not found. Using default config.")
            self.config = {}
        except Exception as e:
            self.logger.error(f"Error loading config file: {e}")
            self.config = {}

        try:
            self.github = Github(token)
            self.org = self.github.get_organization(org_name)
        except Exception as e:
            self.logger.error(f"Failed to initialize GitHub connection: {e}")
            raise

    def generate_report(self) -> List[str]:
        """
        Generate comprehensive health reports for repositories
        
        :return: List of report file paths
        """
        # Scan organization and get results
        df, summary = self.scan_organization()
        
        # Create reports directory if it doesn't exist
        os.makedirs('reports', exist_ok=True)
        
        # Generate timestamp for unique report filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Create summary report
        summary_path = f'reports/summary_{timestamp}.md'
        self._generate_summary_report(summary, summary_path)
        
        # Create detailed repository report
        detailed_path = f'reports/detailed_{timestamp}.csv'
        df.to_csv(detailed_path, index=False)
        
        return [summary_path, detailed_path]

    def _generate_summary_report(self, summary: Dict, path: str):
        """
        Generate a markdown summary report
        
        :param summary: Summary statistics dictionary
        :param path: File path to save the report
        """
        with open(path, mode='w', encoding="utf-8") as f:
            f.write("# Repository Health Check Summary\n\n")
            f.write(f"**Total Repositories**: {summary.get('total_repos', 0)}\n")
            f.write(f"**Archived Repositories**: {summary.get('archived_repos', 0)}\n")
            f.write(f"**Unhealthy Repositories**: {summary.get('unhealthy_repos', 0)}\n")
            
            # Add severity levels
            if summary.get('unhealthy_repos', 0) > 0:
                f.write("\n## Severity\n")
                f.write("🔴 High Risk: Immediate action required\n")

    def scan_organization(self) -> Tuple[pd.DataFrame, Dict[str, int]]:
        """
        Scan repositories in the organization and generate a health report
        
        :return: DataFrame with repository details and summary statistics
        """
        repo_data = []
        ignored_repos = self.config.get('global', {}).get('ignore_repos', [])

        for repo in self.org.get_repos():
            # Skip ignored repositories
            if repo.name in ignored_repos:
                continue

            try:
                # Basic repository health check
                repo_info = {
                    'name': repo.name,
                    'is_archived': repo.archived,
                    'is_healthy': True,
                    'description': repo.description or 'No description',
                    'created_at': repo.created_at,
                    'updated_at': repo.updated_at,
                }

                # Additional health checks
                self._check_repository_age(repo, repo_info)
                self._check_repository_details(repo, repo_info)

                repo_data.append(repo_info)

            except Exception as e:
                self.logger.error(f"Error processing repository {repo.name}: {e}")
                # Add minimal information even if checks fail
                repo_data.append({
                    'name': repo.name,
                    'is_archived': False,
                    'is_healthy': False,
                    'error': str(e)
                })

        # Create DataFrame with default columns
        df = pd.DataFrame(repo_data, columns=[
            'name', 'is_archived', 'is_healthy', 'description', 
            'created_at', 'updated_at', 'error'
        ])

        # Calculate summary
        summary = {
            'total_repos': len(df),
            'archived_repos': df['is_archived'].sum(),
            'unhealthy_repos': (~df['is_healthy']).sum()
        }

        return df, summary

    def _check_repository_age(self, repo, repo_info):
        """
        Check repository age and activity
        
        :param repo: GitHub repository object
        :param repo_info: Dictionary to update with age information
        """
        max_age_days = self.config.get('repository_details', {}).get('max_age_days', 365)
        
        try:
            # Use updated_at as a proxy for activity if no commits are found
            last_activity_date = repo.updated_at

            # Calculate days since last activity
            days_since_activity = (datetime.now(last_activity_date.tzinfo) - last_activity_date).days

            repo_info['days_since_last_activity'] = days_since_activity

            if days_since_activity > max_age_days:
                repo_info['is_healthy'] = False
                repo_info['age_status'] = 'Stale'
            else:
                repo_info['age_status'] = 'Active'

        except Exception as e:
            self.logger.error(f"Age check failed for {repo.name}: {e}")
            repo_info['is_healthy'] = False
            repo_info['age_status'] = 'Unknown'

    def _check_repository_details(self, repo, repo_info):
        """
        Check repository details against configuration
        
        :param repo: GitHub repository object
        :param repo_info: Dictionary to update with repository details
        """
        required_fields = self.config.get('repository_details', {}).get('required_fields', [])
        
        for field in required_fields:
            value = getattr(repo, field, None)
            if not value:
                repo_info['is_healthy'] = False
                self.logger.warning(f"Repository {repo.name} missing required field: {field}")

def main():
    github_token = os.environ.get("GITHUB_TOKEN")
    organization = os.environ.get("ORG_NAME", "mrCDray")

    try:
        checker = RepositoryHealthChecker(github_token, organization)
        report_paths = checker.generate_report()
        
        print("Health check reports generated:")
        for path in report_paths:
            print(f" - {path}")

    except Exception as e:
        logging.error(f"Health check process failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()