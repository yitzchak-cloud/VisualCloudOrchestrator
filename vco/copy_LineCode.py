import os

def gather_code_to_file(root_dir, extensions, output_file, exclude_dirs=None):
    if exclude_dirs is None:
        exclude_dirs = []

    extensions = [ext.lower() for ext in extensions]
    
    try:
        with open(output_file, 'w', encoding='utf-8') as outfile:
            for subdir, dirs, files in os.walk(root_dir):
                # דילוג יעיל על תיקיות מוחרגות
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                
                for file in files:
                    if any(file.lower().endswith(ext) for ext in extensions):
                        filepath = os.path.join(subdir, file)
                        try:
                            with open(filepath, 'r', encoding='utf-8') as infile:
                                outfile.write(f"\n\n# {'='*30}\n")
                                outfile.write(f"# File Path: {filepath}\n")
                                outfile.write(f"# {'='*30}\n\n")
                                outfile.write(infile.read())
                        except Exception as e:
                            print(f"שגיאה בקריאת הקובץ: {filepath} - {e}")
            
            print(f"הסריקה הושלמה בהצלחה. התוכן נשמר ב: {output_file}")
            
    except Exception as e:
        print(f"שגיאה כללית: {e}")

# הגדרות
root_directory = r'C:\Users\isaac\source\repos\VisualCloudOrchestrator\vco' # נתיב הפרויקט שלך
output_filename = 'project_code_summary.txt' # שם קובץ הפלט
file_extensions = ['.py', '.go', '.tf', '.yaml'] # סיומות קבצים לחיפוש
excluded = ['.venv', '.git', '__pycache__', 'node_modules', '.terraform'] # תיקיות להתעלמות

if __name__ == "__main__":
    gather_code_to_file(
        root_dir=root_directory,
        extensions=file_extensions,
        output_file=output_filename,
        exclude_dirs=excluded
    )