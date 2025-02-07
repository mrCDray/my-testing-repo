import os
import yaml
import logging
from typing import Dict, Tuple, Any
from datetime import datetime
import pandas as pd
from github import Github, GithubException


class RepositoryHealthChecker:
    def __init__(self, token: str, org_name: str, config_path: str = "repo_health_config.yml"):
        """
        Initialize the repository health checker with improved error handling

        :param token: GitHub API token
        :param org_name: GitHub organization name
        :param config_path: Path to the health check configuration file
        """
        try:
            self.github = Github(token)
            self.org = self.github.get_organization(org_name)
        except Exception as e:
            logging.error(f"Failed to initialize GitHub connection: {e}")
            raise

        # Load configuration
        try:
            with open(config_path, mode="r", encoding="utf-8") as config_file:
                self.config = yaml.safe_load(config_file)
        except FileNotFoundError:
            logging.error(f"Configuration file {config_path} not found")
            self.config = {}

        # Configure logging
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger(__name__)

    def scan_organization(self) -> Tuple[pd.DataFrame, Dict[str, int]]:
        """
        Scan repositories in the organization and generate a health report with robust error handling

        :return: DataFrame with repository details and summary statistics
        """
        repo_data = []
        ignored_repos = self.config.get("global", {}).get("ignore_repos", [])

        try:
            for repo in self.org.get_repos():
                # Skip ignored repositories
                if repo.name in ignored_repos:
                    continue

                try:
                    repo_info = self._check_repository_health(repo)
                    if repo_info:
                        repo_data.append(repo_info)
                except GithubException as e:
                    # Log specific GitHub API errors without stopping entire process
                    self.logger.warning(f"GitHub API error for repository {repo.name}: {e}")
                except Exception as e:
                    self.logger.error(f"Unexpected error processing repository {repo.name}: {str(e)}")

            # Ensure safe DataFrame creation
            if not repo_data:
                self.logger.warning("No repository data collected")
                return pd.DataFrame(columns=['name', 'is_archived', 'is_healthy']), {}

            # Standardize keys across all dictionaries
            keys = set().union(*repo_data)
            for item in repo_data:
                for key in keys:
                    if key not in item:
                        item[key] = None

            df = pd.DataFrame(repo_data)

            # Safe summary calculation with default values
            summary = {
                "total_repos": len(df),
                "archived_repos": df['is_archived'].fillna(False).sum(),
                "unhealthy_repos": df['is_healthy'].fillna(False).sum()
            }

            return df, summary

        except Exception as e:
            self.logger.error(f"Fatal error in scan_organization: {e}")
            return pd.DataFrame(columns=['name', 'is_archived', 'is_healthy']), {}

    def _check_repository_health(self, repo) -> Dict[str, Any]:
        """
        Perform comprehensive health checks on a repository with fallback mechanisms

        :param repo: GitHub repository object
        :return: Dictionary of repository health details
        """
        health_details = {
            "name": repo.name, 
            "is_archived": repo.archived, 
            "is_healthy": True
        }

        checks = self.config.get("scan", {}).get("checks", [])

        # Use a more defensive approach for each check
        try:
            if "repository_details" in checks:
                self._safe_check_repository_details(repo, health_details)
                self._safe_check_repository_age(repo, health_details)
        except Exception as e:
            self.logger.error(f"Repository details check failed for {repo.name}: {e}")
            health_details['is_healthy'] = False

        # Add more defensive checks for other sections similarly...

        return health_details

    def _safe_check_repository_details(self, repo, health_details):
        """Safely check repository details with fallback"""
        repo_config = self.config.get("repository_details", {})
        required_fields = repo_config.get("required_fields", [])

        for field in required_fields:
            try:
                value = getattr(repo, field, None)
                if not value:
                    health_details["is_healthy"] = False
                    self.logger.warning(f"Repository {repo.name} missing {field}")
            except Exception as e:
                self.logger.error(f"Error checking {field} for {repo.name}: {e}")
                health_details["is_healthy"] = False

    def _safe_check_repository_age(self, repo, health_details):
        """Safely check repository age with comprehensive error handling"""
        try:
            repo_config = self.config.get("repository_details", {})
            max_age_days = repo_config.get("max_age_days")

            if not max_age_days:
                return

            # Fallback mechanism to get latest commit
            try:
                latest_commit = next(iter(repo.get_commits()), None)
                last_commit_date = latest_commit.commit.author.date if latest_commit else repo.created_at
            except Exception:
                last_commit_date = repo.created_at

            days_since_last_commit = (datetime.now(last_commit_date.tzinfo) - last_commit_date).days

            health_details["days_since_last_commit"] = days_since_last_commit
            health_details["created_at"] = repo.created_at

            if days_since_last_commit > max_age_days:
                health_details["is_stale"] = True
                health_details["is_healthy"] = False
                health_details["activity_percentage"] = max(0, 100 - (days_since_last_commit - max_age_days) * 5)
            else:
                health_details["is_stale"] = False
                health_details["activity_percentage"] = 100

        except Exception as e:
            self.logger.error(f"Comprehensive age check failed for {repo.name}: {e}")
            health_details["is_healthy"] = False


def main():
    github_token = os.environ.get("GITHUB_TOKEN")
    organization = os.environ.get("ORG_NAME", "your-org-name")

    try:
        checker = RepositoryHealthChecker(github_token, organization)
        df, summary = checker.scan_organization()

        # Improved output handling
        print("Repository Health Summary:")
        print(yaml.dump(summary))
        print("\nDetailed Repository Health:")
        print(df.to_string())

    except Exception as e:
        logging.error(f"Health check process failed: {e}")


if __name__ == "__main__":
    main()