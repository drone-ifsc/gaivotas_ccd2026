import sys
import json
from pathlib import Path
import shutil

if __name__ == "__main__":
  if len(sys.argv) > 1:
    counter = 0

    json_path = sys.argv[1]
    dir_path = sys.argv[2]
    files = [f.name for f in Path(dir_path).iterdir() if f.is_file()]

    with open(json_path, 'r', encoding='utf-8') as json_file:
        data = json.load(json_file)
        for obj in data:
           filename = str(obj["file_upload"])[9:] 
           if filename in files:
              #shutil.move(dir_path + "/" + filename, dir_path + "/used")
              counter += 1
    json_file.close()
    print(counter)
  else:
    raise ValueError("No file name specified")
  