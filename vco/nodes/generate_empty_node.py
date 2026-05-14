import os
import sys

def generate_empty_node(resource_name):
    # הגדרת נתיבי התיקיות
    base_dir = f"resource/{resource_name}"
    tf_dir = f"{base_dir}/terraform"
    
    # יצירת התיקיות (כולל תיקיות האב אם אינן קיימות)
    os.makedirs(tf_dir, exist_ok=True)
    print(f"Created directories for '{resource_name}'")

    # רשימת הקבצים שיש ליצור לפי הסטנדרט
    files_to_create = [
        f"{base_dir}/__init__.py",
        f"{base_dir}/{resource_name}.py",
        f"{base_dir}/{resource_name}_params.yaml",
        f"{base_dir}/_pulumi.py",
        f"{base_dir}/_terraform.py",
        f"{tf_dir}/main.tf",
        f"{tf_dir}/variables.tf",
        f"{tf_dir}/outputs.tf"
    ]

    # יצירת הקבצים כריקים לחלוטין
    for file_path in files_to_create:
        with open(file_path, "w", encoding="utf-8") as f:
            pass # פתיחה במצב "w" ללא כתיבה מייצרת קובץ ריק
        print(f"Created empty file: {file_path}")

    print(f"\n✅ Successfully generated empty folder structure and files for '{resource_name}'!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_empty_node.py <resource_snake_case>")
        sys.exit(1)
    
    # לוקח את הארגומנט מהטרמינל ומוודא שהוא באותיות קטנות (snake_case)
    resource_input = sys.argv[1].lower()
    generate_empty_node(resource_input)
    
# python generate_empty_node.py artifact_registry