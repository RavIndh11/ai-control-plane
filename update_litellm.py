import re

with open("k8s/templates/02-platform.yaml", "r") as f:
    content = f.read()

# Replace the hardcoded model blocks with the new models
new_models = """    model_list:
      - model_name: qwen3.5:9b
        litellm_params:
          model: ollama/qwen3.5:9b
          api_base: http://${OLLAMA_HOST_IP}:11434
          tpm: 100000
          rpm: 60
      - model_name: gemma4:12b
        litellm_params:
          model: ollama/gemma4:12b
          api_base: http://${OLLAMA_HOST_IP}:11434
          tpm: 100000
          rpm: 40
      - model_name: qwen3-embedding:4b
        litellm_params:
          model: ollama/qwen3-embedding:4b
          api_base: http://${OLLAMA_HOST_IP}:11434
          input_cost_per_token: 0
          output_cost_per_token: 0"""

# Regex to match the model_list section
content = re.sub(r'    model_list:.*?output_cost_per_token: 0', new_models, content, flags=re.DOTALL)

with open("k8s/templates/02-platform.yaml", "w") as f:
    f.write(content)
