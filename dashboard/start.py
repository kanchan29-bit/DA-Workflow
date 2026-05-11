import os
import sys

if __name__ == "__main__":
    # Ensure project root is in PYTHONPATH
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, project_root)
    
    from dashboard.app import app
    print("Starting DA-Workflow Dashboard on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
