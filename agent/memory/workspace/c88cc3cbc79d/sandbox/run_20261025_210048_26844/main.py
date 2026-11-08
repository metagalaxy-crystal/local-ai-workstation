import subprocess
result = subprocess.run(['pip', 'install', 'python-pptx'], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
