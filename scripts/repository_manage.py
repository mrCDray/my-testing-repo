import os
import sys
from typing import Dict, Any, List
import logging
import json
import yaml
from github import Github


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


class RulesetManager:
    """Manages repository rulesets including branch and tag rules"""

    def __init__(self, logger):
        self.logger = logger

    def configure_ruleset(self, ruleset_config: Dict[str, Any]) -> Dict[str, Any]:
        """Configure a single ruleset with all rules"""
        try:
            name = ruleset_config.get("name")
            target = ruleset_config.get("target", "branch")
            enforcement = ruleset_config.get("enforcement", "active")

            ruleset_params = {
                "name": name,
                "target": target,
                "enforcement": enforcement,
                "bypass_actors": ruleset_config.get("bypass_actors", []),
                "conditions": self._prepare_conditions(ruleset_config.get("conditions", {})),
                "rules": self._prepare_rules(ruleset_config.get("rules", [])),
            }

            return ruleset_params

        except Exception as e:
            self.logger.error(f"Error configuring ruleset {name}: {str(e)}")
            raise

    def _prepare_conditions(self, conditions: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare ruleset conditions"""
        prepared_conditions = {}

        if "ref_name" in conditions:
            prepared_conditions["ref_name"] = {
                "include": conditions["ref_name"].get("include", []),
                "exclude": conditions["ref_name"].get("exclude", []),
            }

        return prepared_conditions

    def _prepare_rules(self, rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare ruleset rules with their parameters"""
        prepared_rules = []

        for rule in rules:
            rule_type = rule.get("type")
            if not rule_type:
                continue

            prepared_rule = {"type": rule_type}

            if "parameters" in rule:
                prepared_rule["parameters"] = self._get_rule_parameters(rule_type, rule["parameters"])

            prepared_rules.append(prepared_rule)

        return prepared_rules

    def _get_rule_parameters(self, rule_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get parameters for specific rule types"""
        if rule_type == "pull_request":
            return {
                "dismiss_stale_reviews_on_push": params.get("dismiss_stale_reviews_on_push", True),
                "require_code_owner_review": params.get("require_code_owner_review", True),
                "require_last_push_approval": params.get("require_last_push_approval", True),
                "required_approving_review_count": params.get("required_approving_review_count", 1),
                "required_review_thread_resolution": params.get("required_review_thread_resolution", True),
            }
        if rule_type == "required_status_checks":
            return {
                "strict_required_status_checks_policy": params.get("strict_required_status_checks_policy", True),
                "required_status_checks": params.get("required_status_checks", []),
            }
        # Add other rule type parameters as needed
        return params


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
        self.ruleset_manager = RulesetManager(self.logger)

    def load_repository_config(self, config_path):
        """Load repository configuration from the specified path."""
        try:
            with open(config_path, mode="r", encoding="utf-8") as file:
                config = yaml.safe_load(file)
                return config.get("repository", {})
        except (FileNotFoundError, yaml.YAMLError) as e:
            self.logger.error(f"Error loading repository configuration: {e}")
            raise

    def update_repository_rules(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Update repository rules and protection settings"""
        changes = {}

        try:
            if "rulesets" in config:
                for ruleset_config in config["rulesets"]:
                    ruleset_name = ruleset_config.get("name")
                    if not ruleset_name:
                        continue

                    # Configure ruleset
                    ruleset_params = self.ruleset_manager.configure_ruleset(ruleset_config)

                    # Apply ruleset
                    try:
                        existing_ruleset = next((r for r in repo.get_rulesets() if r.name == ruleset_name), None)

                        if existing_ruleset:
                            existing_ruleset.edit(**ruleset_params)
                            changes[f"ruleset_{ruleset_name}"] = "updated"
                        else:
                            repo.create_ruleset(**ruleset_params)
                            changes[f"ruleset_{ruleset_name}"] = "created"

                    except Exception as e:
                        self.logger.error(f"Error applying ruleset {ruleset_name}: {str(e)}")
                        changes[f"ruleset_{ruleset_name}"] = f"error: {str(e)}"

            return changes

        except Exception as e:
            self.logger.error(f"Error updating repository rules: {str(e)}")
            return {"error": str(e)}

    def update_github_repository(self, repo_name, config):
        try:
            repo = self.org.get_repo(repo_name)

            # Verify repository name matches config
            if config.get("name") != repo_name:
                raise ValueError("Repository name change is not allowed")

            changes = {}

            # Update basic settings
            changes.update(self._update_repository_settings(repo, config))

            # Update rules and protection settings
            changes.update(self.update_repository_rules(repo, config))

            self.logger.info(f"Updated repository {repo_name}")
            return changes

        except Exception as e:
            self.logger.error(f"Error updating repository {repo_name}: {str(e)}")
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
    """Get the list of changed files from the environment and Git."""
    changed_files = []

    # First try to get files from CHANGED_FILES environment variable
    changed_files_env = os.environ.get("CHANGED_FILES")
    if changed_files_env:
        changed_files.extend([f.strip() for f in changed_files_env.split("\n") if f.strip()])
        logging.info(f"Files from CHANGED_FILES env: {changed_files}")

    # Fallback to event payload if available
    if not changed_files:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if event_path:
            try:
                with open(event_path, mode="r", encoding="utf-8") as f:
                    event_data = json.load(f)
                    logging.info(f"Processing event data for changes")

                    # Handle push event specifically
                    if "commits" in event_data:
                        for commit in event_data["commits"]:
                            changed_files.extend(commit.get("modified", []))
                            changed_files.extend(commit.get("added", []))
                            changed_files.extend(commit.get("renamed", []))
            except Exception as e:
                logging.warning(f"Error reading event data: {e}")

    # Remove duplicates and filter for repository config files
    unique_files = list(set(changed_files))
    config_files = [
        f
        for f in unique_files
        if f.startswith("repositories/")
        and f.endswith("/repository.yml")
        and os.path.exists(os.path.join(os.environ.get("GITHUB_WORKSPACE", ""), f))
    ]

    logging.info(f"Final list of repository config files to process: {config_files}")
    return config_files


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
        # Get changed files directly
        config_files = get_changed_files()

        if not config_files:
            logging.warning("No repository configuration files were found in changes")
            sys.exit(0)

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
