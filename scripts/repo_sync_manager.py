import os
import logging
from typing import Dict, Any, List
import yaml
from github import Github
from github.Repository import Repository


class RepoSyncManager:
    def __init__(self, token: str, org_name: str):
        self.github = Github(token)
        self.org = self.github.get_organization(org_name)
        self.logger = logging.getLogger(__name__)
        self.default_config = self._load_default_config()
        
    def sync_repository_configs(self) -> Dict[str, Any]:
        """Sync all repositories based on their individual config files"""
        sync_results = {}
        config_path = "repositories"
        
        try:
            # Walk through all repository config files
            for repo_dir in os.listdir(config_path):
                repo_config_path = os.path.join(config_path, repo_dir, "repository.yml")
                if os.path.exists(repo_config_path):
                    try:
                        with open(repo_config_path, 'r') as f:
                            config = yaml.safe_load(f)
                            repo_name = repo_dir
                            
                            # Get repository and sync settings
                            repo = self.org.get_repo(repo_name)
                            changes = self._sync_repository_with_config(repo, config)
                            
                            if changes:
                                sync_results[repo_name] = changes
                                self.logger.info(f"Synced repository {repo_name}: {changes}")
                                
                    except Exception as e:
                        sync_results[repo_dir] = f"Error: {str(e)}"
                        self.logger.error(f"Error syncing repository {repo_dir}: {str(e)}")
                        
            return sync_results
            
        except Exception as e:
            self.logger.error(f"Error during repository sync: {str(e)}")
            raise

    def _apply_visibility_settings(self, repo: Repository, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply visibility settings to repository"""
        changes = {}
        visibility = config.get("visibility")
        
        if visibility and visibility in ["public", "private", "internal"]:
            try:
                # Get current visibility
                current_visibility = "private" if repo.private else "public"
                if hasattr(repo, "visibility"):
                    current_visibility = repo.visibility
                    
                if current_visibility != visibility:
                    repo.edit(visibility=visibility)
                    changes["visibility"] = f"{current_visibility} → {visibility}"
                    
            except Exception as e:
                self.logger.error(f"Error updating visibility: {str(e)}")
                
        return changes

    def _sync_rulesets(self, repo: Repository, rulesets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sync repository rulesets"""
        changes = {}
        
        try:
            # Get existing rulesets
            existing_rulesets = list(repo.get_rulesets())
            
            for ruleset_config in rulesets:
                ruleset_name = ruleset_config.get("name")
                if not ruleset_name:
                    continue
                    
                # Find matching existing ruleset
                existing_ruleset = next(
                    (r for r in existing_rulesets if r.name == ruleset_name),
                    None
                )
                
                ruleset_params = {
                    "name": ruleset_name,
                    "target": ruleset_config.get("target", "branch"),
                    "enforcement": ruleset_config.get("enforcement", "active"),
                    "conditions": ruleset_config.get("conditions", {}),
                    "rules": ruleset_config.get("rules", [])
                }
                
                if existing_ruleset:
                    # Update existing ruleset
                    existing_ruleset.edit(**ruleset_params)
                    changes[f"ruleset_{ruleset_name}"] = "updated"
                else:
                    # Create new ruleset
                    repo.create_ruleset(**ruleset_params)
                    changes[f"ruleset_{ruleset_name}"] = "created"
                    
            return changes
            
        except Exception as e:
            self.logger.error(f"Error syncing rulesets: {str(e)}")
            return {"error": str(e)}

    def _sync_status_checks(self, repo: Repository, branch_name: str, required_checks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sync required status checks for a branch"""
        changes = {}
        
        try:
            branch = repo.get_branch(branch_name)
            current_protection = branch.get_protection()
            
            # Prepare status checks configuration
            contexts = [check["context"] for check in required_checks]
            strict = any(check.get("strict", False) for check in required_checks)
            
            # Update branch protection with new status checks
            branch.edit_protection(
                strict=strict,
                contexts=contexts,
                enforce_admins=current_protection.enforce_admins.enabled,
                required_approving_review_count=current_protection.required_pull_request_reviews.required_approving_review_count if current_protection.required_pull_request_reviews else None,
                dismiss_stale_reviews=current_protection.required_pull_request_reviews.dismiss_stale_reviews if current_protection.required_pull_request_reviews else False
            )
            
            changes[f"status_checks_{branch_name}"] = f"updated: {', '.join(contexts)}"
            
        except Exception as e:
            self.logger.error(f"Error syncing status checks: {str(e)}")
            changes[f"status_checks_{branch_name}"] = f"error: {str(e)}"
            
        return changes

    def _sync_repository_with_config(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronize repository settings with configuration"""
        changes = {}
        
        try:
            # Update basic repository settings
            repo_config = config.get("repository", {})
            changes.update(self._sync_repo_settings(repo, repo_config))
            
            # Update visibility settings
            changes.update(self._apply_visibility_settings(repo, repo_config))
            
            # Update security settings
            if "security" in repo_config:
                changes.update(self._sync_security_settings(repo, repo_config["security"]))
                
            # Update rulesets
            if "rulesets" in repo_config:
                changes.update(self._sync_rulesets(repo, repo_config["rulesets"]))
                
            # Update required status checks for each branch
            if "status_checks" in repo_config:
                for branch_config in repo_config["status_checks"]:
                    branch_name = branch_config.get("branch")
                    required_checks = branch_config.get("checks", [])
                    if branch_name and required_checks:
                        changes.update(self._sync_status_checks(repo, branch_name, required_checks))
                        
            return changes
            
        except Exception as e:
            self.logger.error(f"Error syncing repository settings: {str(e)}")
            raise