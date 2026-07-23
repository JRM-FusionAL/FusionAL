"""Quick test of FusionAL AI generation"""
from ai_agent import generate_mcp_project

print("🚀 Testing FusionAL AI Generation...\n")

try:
    result = generate_mcp_project(
        prompt="Build a simple joke MCP server with a single tool that returns a random programming joke",
        provider="claude",
        out_dir="./test-joke-server",
        build=False  # Don't build Docker image yet
    )
    
    print("✅ Generation successful!")
    print(f"\n📁 Output directory: {result['out_dir']}")
    print("\n📝 Generated files:")
    for file in result['files']:
        print(f"  - {file}")
    
    print("\n" + "="*60)
    print("Now check the test-joke-server directory for generated code!")
    print("="*60)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
