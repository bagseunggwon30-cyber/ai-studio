"""Launch the external supervisor MCP bridge from any working directory."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio.supervisor_mcp import main
if __name__ == "__main__":
    main()
