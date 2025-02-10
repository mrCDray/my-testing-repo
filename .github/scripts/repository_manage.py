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
            with open(config_path, mode="r", encoding="uft-8") as file:
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
                try:
                    repo.enable_vulnerability_alert()
                except Exception as e:
                    self.logger.warning(f"Could not enable vulnerability alerts: {e}")

            if security_config.get("enableAutomatedSecurityFixes", False):
                try:
                    repo.enable_automated_security_fixes()
                except Exception as e:
                    self.logger.warning(f"Could not enable automated security fixes: {e}")

            # Update topics
            topics = config.get("topics", [])
            if topics:
                repo.replace_topics(topics)

            self.logger.info(f"Updated settings for repository {repo.name}")

        except Exception as e:
            self.logger.warning(f"Could not update all repository settings: {e}")
            raise


def get_changed_files():
    """Get the list of changed files from the GitHub event."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        logging.error("GITHUB_EVENT_PATH environment variable is not set")
        raise ValueError("GITHUB_EVENT_PATH environment variable is not set")

    try:
        with open(event_path, mode="r", encoding="utf-8") as f:
            event_data = json.load(f)
            logging.info(f"GitHub Event Data: {json.dumps(event_data, indent=2)}")

        # Get the list of changed files
        changed_files = []

        # Check commits for changed files
        if "commits" in event_data:
            for commit in event_data["commits"]:
                # Add modified, added, and renamed files
                modified = commit.get("modified", [])
                added = commit.get("added", [])
                renamed = commit.get("renamed", [])

                logging.info(f"Commit {commit.get('id', 'unknown')}:")
                logging.info(f"  Modified files: {modified}")
                logging.info(f"  Added files: {added}")
                logging.info(f"  Renamed files: {renamed}")

                changed_files.extend(modified)
                changed_files.extend(added)
                changed_files.extend(renamed)

        # Remove duplicates
        unique_files = list(set(changed_files))
        logging.info(f"All changed files: {unique_files}")

        # Check for repository configuration files
        config_files = [f for f in unique_files if f.startswith("repositories/") and f.endswith("/repository.yml")]
        logging.info(f"Matched repository configuration files: {config_files}")

        return unique_files
    except Exception as e:
        logging.error(f"Error reading GitHub event data: {e}")
        raise


def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Log environment variables (excluding sensitive data)
    logging.info("Environment Variables:")
    logging.info(f"GITHUB_WORKSPACE: {os.environ.get('GITHUB_WORKSPACE')}")
    logging.info(f"GITHUB_EVENT_PATH: {os.environ.get('GITHUB_EVENT_PATH')}")
    logging.info(f"GITHUB_ORGANIZATION: {os.environ.get('GITHUB_ORGANIZATION')}")

    # Get environment variables
    github_token = os.environ.get("GITHUB_TOKEN")
    github_org = os.environ.get("GITHUB_ORGANIZATION")
    workspace = os.environ.get("GITHUB_WORKSPACE")

    if not all([github_token, github_org, workspace]):
        logging.error("Missing required environment variables")
        sys.exit(1)

    try:
        # List contents of workspace directory
        logging.info("Workspace contents:")
        for root, dirs, files in os.walk(workspace):
            logging.info(f"Directory: {root}")
            for d in dirs:
                logging.info(f"  Dir: {d}")
            for f in files:
                logging.info(f"  File: {f}")

        # Get changed files
        changed_files = get_changed_files()

        # Filter for repository configuration files
        config_files = [f for f in changed_files if f.startswith("repositories/") and f.endswith("/repository.yml")]

        if not config_files:
            logging.error("No repository configuration files were changed")
            sys.exit(1)

        updater = RepositoryUpdater(github_token, github_org)

        # Process each changed configuration file
        for config_file in config_files:
            try:
                # Extract repository name from path (repositories/{repo_name}/repository.yml)
                repo_name = config_file.split("/")[1]

                # Full path to the configuration file
                config_path = os.path.join(workspace, config_file)

                logging.info(f"Processing changes for repository: {repo_name}")

                # Load and validate configuration
                config = updater.load_repository_config(config_path)

                # Update GitHub repository
                updater.update_github_repository(repo_name, config)

            except Exception as e:
                logging.error(f"Error processing repository {repo_name}: {e}")
                # Continue processing other repositories if there are any
                continue

    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
