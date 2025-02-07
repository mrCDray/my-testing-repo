import os
import yaml
import logging
from typing import Dict, Tuple, Any
from datetime import datetime, timedelta
import pandas as pd
from github import Github

class RepositoryHealthChecker:
    def __init__(self, token: str, org_name: str, config_path: str = 'repo_health_config.yml'):
        """
        Initialize the repository health checker
        
        :param token: GitHub API token
        :param org_name: GitHub organization name
        :param config_path: Path to the health check configuration file
        """
        self.github = Github(token)
        self.org = self.github.get_organization(org_name)
        
        # Load configuration
        with open(config_path, mode='r', encoding="utf-8") as config_file:
            self.config = yaml.safe_load(config_file)
        
        # Configure logging
        logging.basicConfig(level=logging.INFO, 
                            format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

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
                repo_info = self._check_repository_health(repo)
                repo_data.append(repo_info)
            except Exception as e:
                self.logger.error(f"Error processing repository {repo.name}: {str(e)}")

        # Create DataFrame
        df = pd.DataFrame(repo_data)

        # Calculate summary statistics
        summary = {
            "total_repos": len(df),
            "archived_repos": df['is_archived'].sum() if 'is_archived' in df.columns else 0,
            "unhealthy_repos": df['is_healthy'].sum() if 'is_healthy' in df.columns else 0
        }

        return df, summary

    def _check_repository_health(self, repo) -> Dict[str, Any]:
        """
        Perform comprehensive health checks on a repository
        
        :param repo: GitHub repository object
        :return: Dictionary of repository health details
        """
        checks = self.config.get('scan', {}).get('checks', [])
        health_details = {
            'name': repo.name,
            'is_archived': repo.archived,
            'is_healthy': True
        }

        # Perform individual checks based on configuration
        if 'repository_details' in checks:
            self._check_repository_details(repo, health_details)
            self._check_repository_age(repo, health_details)

        if 'security_analysis' in checks:
            self._check_security_analysis(repo, health_details)
        
        if 'branch_protection' in checks:
            self._check_branch_protection(repo, health_details)
        
        if 'collaborators' in checks:
            self._check_collaborators(repo, health_details)
        
        if 'workflow_status' in checks:
            self._check_workflow_status(repo, health_details)

        return health_details


    def _check_repository_age(self, repo, health_details: Dict[str, Any]):
        """
        Check repository age and activity level
        
        :param repo: GitHub repository object
        :param health_details: Dictionary to update with age and activity information
        """
        repo_config = self.config.get('repository_details', {})
        max_age_days = repo_config.get('max_age_days')
        
        if not max_age_days:
            return

        try:
            # Get the latest commit
            try:
                latest_commit = repo.get_commits().get_page(0)[0]
                last_commit_date = latest_commit.commit.author.date
            except IndexError:
                # No commits found
                last_commit_date = repo.created_at

            # Calculate days since last commit
            days_since_last_commit = (datetime.now(last_commit_date.tzinfo) - last_commit_date).days

            # Add age-related details to health_details
            health_details['days_since_last_commit'] = days_since_last_commit
            health_details['created_at'] = repo.created_at

            # Determine staleness and activity level
            if days_since_last_commit > max_age_days:
                # Repository is considered stale
                health_details['is_stale'] = True
                health_details['is_healthy'] = False
                
                # Calculate activity percentage
                # The further past max_age_days, the lower the activity percentage
                activity_percentage = max(0, 100 - (days_since_last_commit - max_age_days) * 5)
                health_details['activity_percentage'] = max(0, min(100, activity_percentage))

                self.logger.warning(
                    f"Repository {repo.name} is stale. "
                    f"Last commit was {days_since_last_commit} days ago. "
                    f"Activity level: {health_details['activity_percentage']}%"
                )
            else:
                # Repository is active
                health_details['is_stale'] = False
                health_details['activity_percentage'] = 100

        except Exception as e:
            self.logger.error(f"Error checking repository age for {repo.name}: {str(e)}")
            health_details['is_healthy'] = False


    def _check_repository_details(self, repo, health_details: Dict[str, Any]):
        """Check repository details configuration"""
        repo_config = self.config.get('repository_details', {})
        
        # Check required fields
        required_fields = repo_config.get('required_fields', [])
        for field in required_fields:
            if not getattr(repo, field, None):
                health_details['is_healthy'] = False
                self.logger.warning(f"Repository {repo.name} missing {field}")


    def _check_security_analysis(self, repo, health_details: Dict[str, Any]):
        """Check security analysis features"""
        security_config = self.config.get('security_analysis', {})
        
        # Example security feature checks
        try:
            security_and_analysis = repo.get_security_and_analysis()
            required_features = security_config.get('required_features', [])
            
            for feature in required_features:
                # Implement checks for each security feature
                if not getattr(security_and_analysis, feature, False):
                    health_details['is_healthy'] = False
                    self.logger.warning(f"Security feature {feature} not enabled for {repo.name}")
        except Exception as e:
            health_details['is_healthy'] = False
            self.logger.error(f"Could not retrieve security analysis for {repo.name}: {str(e)}")

    def _check_branch_protection(self, repo, health_details: Dict[str, Any]):
        """
        Check branch protection rules for the repository
        
        :param repo: GitHub repository object
        :param health_details: Dictionary to update with branch protection health
        """
        branch_protection_config = self.config.get('branch_protection', {})
        
        # Initialize branch protection details
        health_details['branch_protection'] = {
            'main_branch_protected': False,
            'protection_rules': {}
        }

        try:
            # Check protection for main branch
            main_branch_name = repo.default_branch or 'main'
            
            try:
                branch_protection = repo.get_branch_protection(main_branch_name)
            except Exception as e:
                # No branch protection found
                self.logger.warning(f"No branch protection found for {main_branch_name} in {repo.name}")
                health_details['is_healthy'] = False
                return

            # Get configured protection rules for main branch
            main_branch_rules = branch_protection_config.get('main', {}).get('required_rules', [])
            
            # Check each protection rule
            protection_checks = {
                'pull_request_reviews': self._check_pr_reviews(branch_protection, main_branch_rules),
                'status_checks': self._check_status_checks(branch_protection, main_branch_rules),
                'require_up_to_date_branch': self._check_up_to_date_branch(branch_protection, main_branch_rules),
                'enforce_admins': self._check_admin_enforcement(branch_protection, main_branch_rules),
                'restrict_pushes': self._check_push_restrictions(branch_protection, main_branch_rules)
            }

            # Update health details
            health_details['branch_protection']['protection_rules'] = protection_checks
            
            # Check if all required protections are in place
            if all(protection_checks.values()):
                health_details['branch_protection']['main_branch_protected'] = True
            else:
                health_details['is_healthy'] = False
                self.logger.warning(f"Incomplete branch protection for {main_branch_name} in {repo.name}")

        except Exception as e:
            self.logger.error(f"Error checking branch protection for {repo.name}: {str(e)}")
            health_details['is_healthy'] = False

    def _check_pr_reviews(self, branch_protection, required_rules):
        """Check pull request review requirements"""
        pr_review_rules = next((rule.get('pull_request_reviews') for rule in required_rules 
                                if 'pull_request_reviews' in rule), None)
        
        if not pr_review_rules:
            return True  # No rules specified, consider it passed
        
        try:
            required_count = pr_review_rules.get('required_approving_review_count', 1)
            return branch_protection.required_pull_request_reviews.required_approving_review_count >= required_count
        except Exception:
            return False

    def _check_status_checks(self, branch_protection, required_rules):
        """Check required status checks"""
        status_check_rules = next((rule.get('status_checks') for rule in required_rules 
                                    if 'status_checks' in rule), None)
        
        if not status_check_rules:
            return True  # No rules specified, consider it passed
        
        try:
            required_contexts = status_check_rules.get('contexts', [])
            current_contexts = branch_protection.required_status_checks.contexts
            
            # Check if all required contexts are present
            return all(context in current_contexts for context in required_contexts)
        except Exception:
            return False

    def _check_up_to_date_branch(self, branch_protection, required_rules):
        """Check if up-to-date branch is required"""
        up_to_date_rule = next((rule.get('require_up_to_date_branch') for rule in required_rules 
                                if 'require_up_to_date_branch' in rule), None)
        
        if up_to_date_rule is None:
            return True  # No rule specified, consider it passed
        
        try:
            return branch_protection.required_status_checks.strict
        except Exception:
            return False

    def _check_admin_enforcement(self, branch_protection, required_rules):
        """Check if admin enforcement is required"""
        admin_rule = next((rule.get('enforce_admins') for rule in required_rules 
                        if 'enforce_admins' in rule), None)
        
        if admin_rule is None:
            return True  # No rule specified, consider it passed
        
        try:
            return branch_protection.enforce_admins.enabled
        except Exception:
            return False

    def _check_push_restrictions(self, branch_protection, required_rules):
        """Check push restrictions"""
        push_restriction_rule = next((rule.get('restrict_pushes') for rule in required_rules 
                                    if 'restrict_pushes' in rule), None)
        
        if push_restriction_rule is None:
            return True  # No rule specified, consider it passed
        
        try:
            # This is a simplified check and may need to be adjusted based on exact requirements
            return branch_protection.restrictions is not None
        except Exception:
            return False

    def _check_collaborators(self, repo, health_details: Dict[str, Any]):
        """Check collaborator count"""
        collab_config = self.config.get('collaborators', {})
        collaborators = list(repo.get_collaborators())
        
        min_collab = collab_config.get('min_collaborators', 0)
        max_collab = collab_config.get('max_collaborators')
        
        if len(collaborators) < min_collab or (max_collab and len(collaborators) > max_collab):
            health_details['is_healthy'] = False
            self.logger.warning(f"Collaborator count for {repo.name} not within expected range")

    def _check_workflow_status(self, repo, health_details: Dict[str, Any]):
        """Check workflow runs and status"""
        workflow_config = self.config.get('workflow_status', {})
        required_workflows = workflow_config.get('required_workflows', [])
        max_failed_runs = workflow_config.get('max_failed_runs', 3)

        # Implement workflow status checks
        # This would involve retrieving workflow runs and checking their status

def main():
    github_token = os.environ.get('GITHUB_TOKEN')
    organization = 'your-org-name'
    
    checker = RepositoryHealthChecker(github_token, organization)
    df, summary = checker.scan_organization()
    
    # Output or process results
    print("Repository Health Summary:")
    print(yaml.dump(summary))
    print("\nDetailed Repository Health:")
    print(df.to_string())

if __name__ == '__main__':
    main()