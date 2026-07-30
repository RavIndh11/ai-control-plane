# Repo Init Report

## Summary
- repo_root: .
- detected_languages: node, python
- detected_build_tools: npm, pip
- verify_commands: 2

## Detected signals
- .github/workflows/garak-scan.yml:1-1 | risk path .github/workflows | 
- .github/workflows/garak-scan.yml:17-17 | ci run step | echo "In a real environment, you would stand up the agent-orchestrator"
- .github/workflows/garak-scan.yml:30-30 | ci run step | python -m garak \
- apps/agent-orchestrator/requirements.txt:1-1 | requirements.txt present | langchain
- apps/dashboard/package.json:20-20 | package.json scripts | "scripts": {
- apps/dashboard/package.json:23-23 | package.json script test | "test": "react-scripts test",
- infra/cluster/main.tf:1-1 | risk path infra | 
- k8s/templates/00-namespace-and-secrets.yaml:1-1 | risk path k8s | 

## Evidence
- risk_path: .github/workflows/ | .github/workflows/garak-scan.yml:1-1
- detected_build_tool: pip | apps/agent-orchestrator/requirements.txt:1-1
- verify_command: {'cwd': '.', 'command': ['python3', '-m', 'pytest', '-q']} | apps/agent-orchestrator/requirements.txt:1-1
- detected_build_tool: npm | apps/dashboard/package.json:20-20
- detected_node_script: test | apps/dashboard/package.json:23-23
- verify_command: {'cwd': '.', 'command': ['npm', 'test']} | apps/dashboard/package.json:23-23
- risk_path: infra/ | infra/cluster/main.tf:1-1
- risk_path: k8s/ | k8s/templates/00-namespace-and-secrets.yaml:1-1

## Proposed verify pipeline
- python3 -m pytest -q (from requirements.txt present)
- npm test (from package.json script test)

## Proposed risk paths
- .github/workflows/
- infra/
- k8s/

## AGENTS.md status
- status: missing
- AGENTS.md not found
- action: run agentctl bootstrap to create/update policy block

