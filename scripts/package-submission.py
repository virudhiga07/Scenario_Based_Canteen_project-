"""Build a portable academic deliverable without credentials or generated runtimes."""
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parents[1]
output=root/'outputs/virudhigakv-canteen-submission.zip'
output.parent.mkdir(exist_ok=True)
folders=['web','server','java','database','analysis','docs','samples','tests','scripts','drizzle']
exclude={'__pycache__','.pytest_cache','.venv','lib','build','node_modules','.local','outputs'}
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
 z.writestr('virudhigakv-canteen/.openai/hosting.json', '{"d1":"DB","r2":null}\n')
 for folder in folders:
  for file in sorted((root/folder).rglob('*')):
   relative=file.relative_to(root)
   if file.is_file() and not exclude.intersection(relative.parts) and (file.suffix not in {'.db','.sqlite','.pyc','.class','.jar'} or str(relative)=='samples/canteen-demo.db'):
    z.write(file,Path('virudhigakv-canteen')/relative)
 for filename in ['README.md','requirements.txt','package.json','.gitignore']:
  if (root/filename).exists():z.write(root/filename,Path('virudhigakv-canteen')/filename)
print(output)
