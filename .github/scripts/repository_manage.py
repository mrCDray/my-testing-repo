import os
import sys
import logging
import json
import yaml

from github import Github, GithubException


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


class RepositoryUpdater:
    def __init__(self, github_token, organization):
        self.g = Github(github_token)
        self.org = self.g.get_organization(organization)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("repository_update.log")],
        )
        self.logger = logging.getLogger(__name__)

    def load_repository_config(self, config_path):
        """Load repository configuration from the specified path."""
        try:
            with open(config_path, mode="r", encoding="utf-8") as file:
                config = yaml.safe_load(file)
                return config.get("repository", {})
        except (FileNotFoundError, yaml.YAMLError) as e:
            self.logger.error(f"Error loading repository configuration: {e}")
            raise

    def update_github_repository(self, repo_name, config):
        """Update an existing GitHub repository with new configuration."""
        try:
            # Get existing repository
            repo = self.org.get_repo(repo_name)

            # Verify repository name matches config
            if config.get("name") != repo_name:
                raise ValueError("Repository name change is not allowed")

            # Update repository settings
            self._update_repository_settings(repo, config)

            self.logger.info(f"Updated repository {repo_name}")
            return repo

        except GithubException as e:
            self.logger.error(f"Error accessing repository {repo_name}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error updating repository {repo_name}: {e}")
            raise

    def _update_repository_settings(self, repo, config):
        """Update repository settings based on configuration."""
        try:
            # Update basic settings
            repo.edit(
                has_issues=config.get("has_issues", repo.has_issues),
                has_projects=config.get("has_projects", repo.has_projects),
                has_wiki=config.get("has_wiki", repo.has_wiki),
                default_branch=config.get("default_branch", repo.default_branch),
                allow_squash_merge=config.get("allow_squash_merge", repo.allow_squash_merge),
                allow_merge_commit=config.get("allow_merge_commit", repo.allow_merge_commit),
                allow_rebase_merge=config.get("allow_rebase_merge", repo.allow_rebase_merge),
                allow_auto_merge=config.get("allow_auto_merge", repo.allow_auto_merge),
                delete_branch_on_merge=config.get("delete_branch_on_merge", repo.delete_branch_on_merge),
                allow_update_branch=config.get("allow_update_branch", repo.allow_update_branch),
            )

            # Update security settings
            security_config = config.get("security", {})
            if security_config.get("enableVulnerabilityAlerts", False):
                repo.enable_vulnerability_alert()
            if security_config.get("enableAutomatedSecurityFixes", False):
                repo.enable_automated_security_fixes()

            # Update topics
            topics = config.get("topics", [])
            if topics:
                repo.replace_topics(topics)

            self.logger.info(f"Updated settings for repository {repo.name}")

        except Exception as e:
            self.logger.warning(f"Could not update all repository settings: {e}")
            raise


def main():
    # Get environment variables
    github_token = os.environ.get("GITHUB_TOKEN")
    github_org = os.environ.get("GITHUB_ORGANIZATION")
    workspace = os.environ.get("GITHUB_WORKSPACE", os.getcwd())

    # Get changed file path from GitHub event
    github_event_path = os.environ.get("GITHUB_EVENT_PATH")

    if not all([github_token, github_org, github_event_path]):
        logging.error("Missing required environment variables")
        sys.exit(1)

    try:
        # Read GitHub event data to get changed file
        with open(github_event_path, mode="r", encoding="utf-8") as f:


            event_data = json.load(f)

        # Find changed repository configuration file
        changed_files = event_data.get("push", {}).get("files", [])
        config_file = None
        repo_name = None

        for file in changed_files:
            file_path = file.get("filename", "")
            if file_path.startswith("repositories/") and file_path.endswith("/repository.yml"):
                config_file = os.path.join(workspace, file_path)
                repo_name = file_path.split("/")[1]
                break

        if not config_file or not repo_name:
            logging.error("No repository configuration file found in changes")
            sys.exit(1)

        updater = RepositoryUpdater(github_token, github_org)

        # Load and validate configuration
        config = updater.load_repository_config(config_file)

        # Update GitHub repository
        updater.update_github_repository(repo_name, config)

    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
