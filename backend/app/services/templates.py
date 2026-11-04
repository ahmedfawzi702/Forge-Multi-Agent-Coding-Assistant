import json


def template_files(template: str, name: str) -> dict[str, str]:
    """Small transparent starters; creation never runs package managers."""
    if template == "empty":
        return {}
    if template == "python":
        return {"main.py": 'def main():\n    print("Hello from Forge")\n\n\nif __name__ == "__main__":\n    main()\n',
                "test_main.py": 'from main import main\n\n\ndef test_main(capsys):\n    main()\n    assert "Hello from Forge" in capsys.readouterr().out\n',
                "requirements.txt": "pytest>=8\n", ".gitignore": ".venv/\n__pycache__/\n.pytest_cache/\n"}
    if template == "fastapi":
        return {"app/__init__.py": "", "app/main.py": 'from fastapi import FastAPI\n\napp = FastAPI()\n\n\n@app.get("/health")\ndef health():\n    return {"status": "ok"}\n',
                "tests/test_health.py": 'from fastapi.testclient import TestClient\nfrom app.main import app\n\n\ndef test_health():\n    assert TestClient(app).get("/health").json() == {"status": "ok"}\n',
                "requirements.txt": "fastapi\nuvicorn\nhttpx\npytest\n",
                "README.md": f"# {name}\n\nInstall requirements in a project virtual environment.\nRun `python -m uvicorn app.main:app --reload`.\nRun `python -m pytest`.\n"}
    package: dict[str, object] = {"name": "forge-project", "private": True, "version": "0.1.0", "type": "module"}
    if template == "node":
        package["scripts"] = {"start": "node index.js", "test": "node --test"}
        return {"package.json": json.dumps(package, indent=2) + "\n", "index.js": 'export const greet = name => `Hello ${name}`;\nconsole.log(greet("Forge"));\n',
                "index.test.js": 'import { test } from "node:test";\nimport assert from "node:assert/strict";\nimport { greet } from "./index.js";\ntest("greeting", () => assert.equal(greet("Ada"), "Hello Ada"));\n'}
    if template == "next":
        package.update({"scripts": {"dev": "next dev --hostname 127.0.0.1", "build": "next build", "start": "next start --hostname 127.0.0.1"},
                        "dependencies": {"next": "^16.4.2", "react": "^19.2.0", "react-dom": "^19.2.0"}})
        return {"package.json": json.dumps(package, indent=2) + "\n",
                "app/layout.jsx": 'export const metadata = { title: "My app" };\nexport default function Layout({children}) { return <html lang="en"><body>{children}</body></html>; }\n',
                "app/page.jsx": 'export default function Home() { return <main><h1>Start building.</h1></main>; }\n',
                ".gitignore": "node_modules/\n.next/\n"}
    package.update({"scripts": {"dev": "vite --host 127.0.0.1", "build": "vite build"},
                    "dependencies": {"react": "^19.2.0", "react-dom": "^19.2.0"}, "devDependencies": {"vite": "^7.0.0"}})
    return {"package.json": json.dumps(package, indent=2) + "\n", "index.html": '<html lang="en"><head><title>My app</title></head><body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body></html>\n',
            "src/main.jsx": 'import React from "react";\nimport { createRoot } from "react-dom/client";\ncreateRoot(document.getElementById("root")).render(<h1>Start building.</h1>);\n', ".gitignore": "node_modules/\ndist/\n"}
