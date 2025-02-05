import os
import yaml
import sys
import logging
from github import Github, GithubException
from github.Repository import Repository
from github.GitRef import GitRef

class RepositoryConfigManager:
    def __init__(self, github_token, organization):
        """
        Initialize the repository configuration manager.
        
        :param github_token: GitHub Personal Access Token with repo and org permissions
        :param organization: GitHub organization name
        """
        self.g = Github(github_token)
        self.org = self.g.get_organization(organization)
        logging.basicConfig(level=logging.INFO, 
                            format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    def load_default_config(self, config_path='default_repository.yml'):
        """
        Load the default repository configuration.
        
        :param config_path: Path to the default repository configuration file
        :return: Parsed configuration dictionary
        """
        try:
            with open(config_path, 'r') as file:
                return yaml.safe_load(file)['repository']
        except FileNotFoundError:
            self.logger.error(f"Default configuration file not found at {config_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            self.logger.error(f"Error parsing YAML file: {e}")
            sys.exit(1)

    def ensure_repo_config_directory(self, repo_name):
        """
        Ensure the repositories configuration directory exists.
        
        :param repo_name: Name of the repository
        """
        config_dir = f'repositories/{repo_name}'
        os.makedirs(config_dir, exist_ok=True)

    def save_repo_config(self, repo: Repository, repo_name: str, config: dict):
        """
        Save repository-specific configuration and commit to the repository.
        
        :param repo: GitHub Repository object
        :param repo_name: Name of the repository
        :param config: Configuration dictionary to save
        """
        # Ensure configuration directory exists
        self.ensure_repo_config_directory(repo_name)
        
        # Local configuration file path
        config_path = f'repositories/{repo_name}/repository.yml'
        
        # Save configuration locally
        with open(config_path, 'w') as file:
            yaml.dump({'repository': config}, file, default_flow_style=False)
        
        # Commit the configuration file to the repository
        self._commit_config_to_repo(repo, config_path, repo_name)
        
        self.logger.info(f"Saved and committed configuration for {repo_name}")

    def _commit_config_to_repo(self, repo: Repository, config_path: str, repo_name: str):
        """
        Commit the configuration file to the repository.
        
        :param repo: GitHub Repository object
        :param config_path: Path to the local configuration file
        :param repo_name: Name of the repository
        """
        try:
            # Get the default branch
            default_branch = repo.get_branch(repo.default_branch)
            
            # Read the configuration file content
            with open(config_path, 'r') as file:
                config_content = file.read()
            
            # Prepare the commit
            commit_message = f"Add repository configuration for {repo_name}"
            config_file_path = f'repositories/{repo_name}/repository.yml'
            
            # Try to get the current file if it exists
            try:
                current_file = repo.get_contents(config_file_path, ref=default_branch.commit.sha)
                # File exists, update it
                repo.update_file(
                    path=config_file_path,
                    message=commit_message,
                    content=config_content,
                    sha=current_file.sha,
                    branch=repo.default_branch
                )
            except GithubException:
                # File doesn't exist, create it
                repo.create_file(
                    path=config_file_path,
                    message=commit_message,
                    content=config_content,
                    branch=repo.default_branch
                )
            
            self.logger.info(f"Committed configuration file for {repo_name}")
        
        except Exception as e:
            self.logger.error(f"Error committing configuration for {repo_name}: {e}")
            # Don't exit, as this is not a critical failure

    def create_or_update_repository(self, repo_name, default_config):
        """
        Create a new repository or update an existing one based on configuration.
        
        :param repo_name: Name of the repository
        :param default_config: Default configuration dictionary
        """
        try:
            # Check if repository exists
            try:
                repo = self.org.get_repo(repo_name)
                self.logger.info(f"Repository {repo_name} already exists.")
                update_mode = True
            except GithubException:
                # Repository doesn't exist, create it
                repo = self.org.create_repo(
                    name=repo_name,
                    private=default_config.get('visibility', 'private') == 'private',
                    auto_init=True  # Initialize with README
                )
                self.logger.info(f"Created new repository {repo_name}")
                update_mode = False

            # Save and commit repository-specific configuration
            self.save_repo_config(repo, repo_name, default_config)

            # Update repository settings
            self._update_repo_settings(repo, default_config)

        except Exception as e:
            self.logger.error(f"Error processing repository {repo_name}: {e}")
            sys.exit(1)

    def _update_repo_settings(self, repo: Repository, config: dict):
        """
        Update repository settings based on configuration.
        
        :param repo: GitHub Repository object
        :param config: Configuration dictionary
        """
        # Mapping of configuration keys to repository edit parameters
        setting_map = {
            "has_issues": "has_issues",
            "has_projects": "has_projects",
            "has_wiki": "has_wiki",
            "default_branch": "default_branch",
            "allow_squash_merge": "allow_squash_merge",
            "allow_merge_commit": "allow_merge_commit",
            "allow_rebase_merge": "allow_rebase_merge",
            "allow_auto_merge": "allow_auto_merge",
            "delete_branch_on_merge": "delete_branch_on_merge",
            "allow_update_branch": "allow_update_branch",
            "archived": "archived",
        }

        # Prepare edit parameters
        edit_params = {
            github_param: config.get(config_key, getattr(repo, github_param))
            for config_key, github_param in setting_map.items()
        }

        # Remove default_branch from edit_params for newly created repos
        if not repo.get_branches():
            edit_params.pop("default_branch", None)

        # Update security settings
        if config.get("security", {}).get("enableVulnerabilityAlerts", False):
            try:
                repo.enable_vulnerability_alert()
            except Exception as e:
                self.logger.warning(f"Could not enable vulnerability alerts: {e}")

        if config.get("security", {}).get("enableAutomatedSecurityFixes", False):
            try:
                repo.enable_automated_security_fixes()
            except Exception as e:
                self.logger.warning(f"Could not enable automated security fixes: {e}")

        # Update repository topics
        topics = config.get("topics", [])
        if topics:
            repo.replace_topics(topics)

        # Edit repository settings, handling potential branch issues
        try:
            repo.edit(**edit_params)
            self.logger.info(f"Updated repository settings for {repo.name}")
        except GithubException as e:
            # Log the specific error, but don't exit
            self.logger.warning(f"Could not update all repository settings: {e}")


def main():
    # These should be passed as environment variables or arguments
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
    GITHUB_ORGANIZATION = os.environ.get('GITHUB_ORGANIZATION')
    
    if not GITHUB_TOKEN or not GITHUB_ORGANIZATION:
        logging.error("GitHub Token or Organization not provided")
        sys.exit(1)

    manager = RepositoryConfigManager(GITHUB_TOKEN, GITHUB_ORGANIZATION)
    
    # Load default configuration
    default_config = manager.load_default_config()
    
    # Example: Create or update a specific repository
    repo_name = os.environ.get('REPOSITORY_NAME', default_config['name'])
    manager.create_or_update_repository(repo_name, default_config)

if __name__ == '__main__':
    main()