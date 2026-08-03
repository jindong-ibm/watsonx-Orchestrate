# Autonomous QA Agents - Quick Start Guide

Get started with the Autonomous QA Agents system in 5 minutes.

## Prerequisites

- watsonx Orchestrate ADK v1.15.0 or higher
- Python 3.9 or higher
- Access to watsonx Orchestrate instance

## Installation

### Step 1: Install Dependencies

```bash
cd autonomous_qa_agents
pip install -r requirements.txt
```

### Step 2: Import Agents and Tools

```bash
./import-all.sh
```

You should see output like:
```
✓ orchestrate CLI found
✓ analyze_requirements imported
✓ parse_release_notes imported
✓ detect_api_changes imported
✓ generate_functional_tests imported
✓ generate_regression_tests imported
✓ generate_edge_cases imported
✓ test_generation_agent imported
✓ exploratory_testing_agent imported
✓ nfr_assessment_agent imported
✓ qa_coordinator_agent imported
```

### Step 3: Verify Installation

```bash
orchestrate agents list | grep qa
```

You should see:
- `test_generation_agent`
- `exploratory_testing_agent`
- `nfr_assessment_agent`
- `qa_coordinator_agent`

## Your First QA Session

### Example 1: Generate Tests from Requirements

1. **Invoke the Test Generation Agent**:
```bash
orchestrate agents invoke test_generation_agent
```

2. **Provide your requirements**:
```
Generate test cases for a login feature with the following requirements:
- Users must provide email and password
- Email must be valid format
- Password must be at least 8 characters
- System must lock account after 5 failed attempts
- Successful login redirects to dashboard
```

3. **Review the generated tests**:
The agent will provide:
- Functional test cases
- Edge case tests
- Validation tests
- Test scripts (if applicable)

### Example 2: Quick Exploratory Test

1. **Invoke the Exploratory Testing Agent**:
```bash
orchestrate agents invoke exploratory_testing_agent
```

2. **Describe what to test**:
```
Explore the login page at https://app.example.com/login
Focus on:
- Input validation
- Error messages
- Security issues
```

3. **Review findings**:
The agent will report:
- Issues discovered
- Severity levels
- Reproduction steps
- Recommendations

### Example 3: Comprehensive QA

1. **Invoke the QA Coordinator Agent**:
```bash
orchestrate agents invoke qa_coordinator_agent
```

2. **Request comprehensive QA**:
```
Run comprehensive QA for our new payment feature:

Requirements:
- Accept credit card payments
- Validate card numbers
- Support Visa, Mastercard, Amex
- Amount range: $0.01 to $10,000
- Send email confirmations

Application URL: https://app.example.com/payment
Scope: Full QA (functional, exploratory, performance)
```

3. **Review consolidated report**:
The coordinator will provide:
- Test generation results
- Exploratory testing findings
- Performance assessment
- Overall quality score
- Recommendations

## Common Use Cases

### Use Case 1: New Feature Testing
```
Agent: test_generation_agent
Input: Requirements document
Output: Complete test suite
```

### Use Case 2: Bug Fix Validation
```
Agent: test_generation_agent
Input: Release notes with bug fixes
Output: Regression test suite
```

### Use Case 3: API Testing
```
Agent: test_generation_agent
Input: Old and new API specifications
Output: API change tests
```

### Use Case 4: Issue Discovery
```
Agent: exploratory_testing_agent
Input: Application URL and focus areas
Output: Discovered issues and findings
```

### Use Case 5: Performance Validation
```
Agent: nfr_assessment_agent
Input: Test scenarios and targets
Output: Performance report
```

### Use Case 6: Release Validation
```
Agent: qa_coordinator_agent
Input: All release artifacts
Output: Comprehensive QA report
```

## Tips for Success

### 1. Be Specific
❌ "Test the app"
✅ "Test the login feature with focus on validation and security"

### 2. Provide Context
❌ "Generate tests"
✅ "Generate tests for the payment API based on these requirements: [paste requirements]"

### 3. Set Priorities
❌ "Test everything"
✅ "Focus on critical security and payment flows first"

### 4. Use the Right Agent
- **Test Generation**: When you need test cases
- **Exploratory Testing**: When you need to find issues
- **NFR Assessment**: When you need performance data
- **QA Coordinator**: When you need everything

## Next Steps

1. ✅ Complete this quick start
2. 📖 Read [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md) for detailed examples
3. 📚 Review [README.md](README.md) for architecture details
4. 🔧 Customize agents for your specific needs
5. 🚀 Integrate into your CI/CD pipeline

## Troubleshooting

### Problem: Import script fails
**Solution**: Ensure watsonx Orchestrate ADK is installed and configured

### Problem: Agent not found
**Solution**: Run `./import-all.sh` again

### Problem: Tests are too generic
**Solution**: Provide more detailed requirements and examples

### Problem: Need help
**Solution**: Check [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md) or contact support

## What's Next?

Now that you've completed the quick start:

- Explore more [usage examples](USAGE_EXAMPLES.md)
- Learn about the [architecture](README.md#architecture)
- Customize agents for your workflow
- Share feedback with your team

Happy testing! 🎉