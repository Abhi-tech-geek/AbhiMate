import sys
from agents.test_generator_agent import TestGeneratorAgent
from agents.execution_agent import ExecutionAgent
from agents.bug_analyzer_agent import BugAnalyzerAgent
from agents.reporting_agent import ReportingAgent

def main():
    print("========================================")
    print("Welcome to the Multi-Agent QA Platform")
    print("========================================")
    
    try:
        feature_description = input("\nPlease describe the feature or URL you want to test:\n> ")
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
        
    if not feature_description.strip():
        print("Error: Input cannot be empty.")
        sys.exit(1)
        
    print("\n--- PHASE 1: GENERATION ---")
    gen_agent = TestGeneratorAgent()
    try:
        gen_agent.generate(feature=feature_description)
    except Exception as e:
        print(f"Generator failed: {e}")
        sys.exit(1)
        
    print("\n--- PHASE 2: EXECUTION ---")
    exec_agent = ExecutionAgent()
    try:
        exec_agent.execute()
    except Exception as e:
        print(f"Executor failed: {e}")
        
    print("\n--- PHASE 3: ANALYSIS ---")
    analyzer_agent = BugAnalyzerAgent()
    try:
        analyzer_agent.analyze()
    except Exception as e:
        print(f"Analyzer failed: {e}")
        
    print("\n--- PHASE 4: REPORTING ---")
    reporting_agent = ReportingAgent()
    try:
        reporting_agent.report()
    except Exception as e:
        print(f"Reporting failed: {e}")

if __name__ == "__main__":
    main()
