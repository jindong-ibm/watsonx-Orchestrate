# Autonomous QA Agents - Usage Examples

This document provides practical examples of using the Autonomous QA Agents system.

## Table of Contents
- [Getting Started](#getting-started)
- [Test Generation Examples](#test-generation-examples)
- [Exploratory Testing Examples](#exploratory-testing-examples)
- [Performance Testing Examples](#performance-testing-examples)
- [Comprehensive QA Examples](#comprehensive-qa-examples)

## Getting Started

### Installation

1. Install dependencies:
```bash
cd autonomous_qa_agents
pip install -r requirements.txt
```

2. Import all agents and tools:
```bash
./import-all.sh
```

3. Verify installation:
```bash
orchestrate agents list | grep qa
orchestrate tools list | grep test
```

## Test Generation Examples

### Example 1: Generate Tests from Requirements

**Scenario**: You have a requirements document for a new payment feature.

**Input to Test Generation Agent**:
```
Generate comprehensive test cases for the following requirements:

Feature: Payment Processing
- The system shall accept credit card payments
- The system must validate card numbers using Luhn algorithm
- The system should support Visa, Mastercard, and Amex
- Payment amounts must be between $0.01 and $10,000
- Failed payments must be logged with error codes
- Users must receive email confirmation for successful payments

User Story:
As a customer, I want to pay with my credit card, so that I can complete my purchase.

Acceptance Criteria:
- Given a valid credit card, when I submit payment, then the transaction succeeds
- Given an invalid card number, when I submit payment, then I see a clear error message
- Given a payment over $10,000, when I submit payment, then it is rejected
```

**Expected Output**:
- Functional test suite with 15-20 test cases
- Edge case tests for boundary values ($0.01, $10,000, $10,000.01)
- Validation tests for card number formats
- Error handling tests
- Executable pytest scripts

### Example 2: Generate Regression Tests from Release Notes

**Input to Test Generation Agent**:
```
Generate regression tests for version 2.5.0:

Release Notes:
## New Features
- Added support for Apple Pay
- Implemented recurring payment schedules

## Bug Fixes
- Fixed issue where refunds were not processing correctly (#1234)
- Corrected tax calculation for international orders (#1235)

## Breaking Changes
- Removed deprecated v1 payment API
- Changed response format for payment status endpoint
```

**Expected Output**:
- Regression test suite with priority matrix
- Tests for bug fixes to prevent regression
- Tests for breaking changes
- Migration tests for deprecated API
- Execution plan with phases

### Example 3: Generate Tests for API Changes

**Input to Test Generation Agent**:
```
Compare these API specifications and generate tests:

Old API:
GET /api/v1/payments
- param: user_id (string) [required]
- param: status (string) [optional]

New API:
GET /api/v2/payments
- param: user_id (string) [required]
- param: status (string) [required]
- param: date_from (date) [optional]
- param: date_to (date) [optional]
```

**Expected Output**:
- API change analysis
- Tests for new required parameter
- Tests for new optional parameters
- Backward compatibility tests
- Breaking change warnings

## Exploratory Testing Examples

### Example 4: Explore Web Application

**Input to Exploratory Testing Agent**:
```
Perform exploratory testing on the checkout flow at https://shop.example.com

Focus areas:
- User registration and login
- Product search and filtering
- Shopping cart operations
- Checkout process
- Payment processing

Look for:
- Functional issues
- Usability problems
- Security vulnerabilities
- Edge cases
```

**Expected Output**:
- Detailed findings report
- Issues categorized by severity
- Reproduction steps for each issue
- Screenshots/evidence
- Recommendations

### Example 5: Explore REST API

**Input to Exploratory Testing Agent**:
```
Explore the User Management API at https://api.example.com/v1/users

Endpoints:
- POST /users (create user)
- GET /users/{id} (get user)
- PUT /users/{id} (update user)
- DELETE /users/{id} (delete user)

Test for:
- Authentication and authorization
- Input validation
- Error handling
- Rate limiting
- Security issues (injection, XSS, etc.)
```

**Expected Output**:
- API exploration report
- Security findings
- Validation gaps
- Error handling issues
- Unexpected behaviors

## Performance Testing Examples

### Example 6: Baseline Performance Test

**Input to NFR Assessment Agent**:
```
Establish performance baseline for the Search API:

Endpoint: GET /api/search?q={query}
Expected load: 100 concurrent users
Target response time: < 500ms (95th percentile)
Target throughput: > 200 requests/second

Test scenarios:
1. Simple keyword search
2. Complex multi-filter search
3. Search with pagination
```

**Expected Output**:
- Baseline metrics report
- Response time percentiles
- Throughput measurements
- Resource utilization
- Bottleneck analysis

### Example 7: Load and Stress Testing

**Input to NFR Assessment Agent**:
```
Run load and stress tests on the Order Processing API:

Baseline: 50 concurrent users
Load test: 200 concurrent users (expected peak)
Stress test: 500 concurrent users (2.5x expected)

Monitor:
- Response times
- Error rates
- Database connections
- CPU and memory usage
- Queue depths

Duration: 30 minutes per test
```

**Expected Output**:
- Load test results
- Stress test results
- Breaking point identification
- Resource utilization graphs
- Scalability recommendations

## Comprehensive QA Examples

### Example 8: Full QA for New Feature

**Input to QA Coordinator Agent**:
```
Run comprehensive QA for the new Subscription Management feature:

Requirements: [attach requirements.pdf]
Release Notes: Version 3.0.0 - Added subscription management
API Spec: [attach openapi.yaml]
Application URL: https://app.example.com/subscriptions

Scope: Full QA (functional, exploratory, performance)
Priority: High (production release)
```

**Workflow**:
1. Coordinator delegates to Test Generation Agent
   - Generates 50+ functional tests
   - Generates 20+ edge case tests
   
2. Coordinator delegates to Exploratory Testing Agent
   - Discovers 5 usability issues
   - Finds 2 security concerns
   
3. Coordinator delegates to NFR Assessment Agent
   - Runs performance tests
   - Identifies 1 bottleneck
   
4. Coordinator consolidates findings
   - 2 critical issues (security)
   - 3 high priority issues
   - 5 medium priority issues
   - Overall quality score: 75/100
   - Recommendation: Fix critical issues before release

### Example 9: Quick Regression Check

**Input to QA Coordinator Agent**:
```
Quick regression check for hotfix release:

Changes: Fixed critical bug in payment processing (#5678)
Scope: Regression testing only
Priority: Critical (hotfix)
Timeline: 2 hours
```

**Workflow**:
1. Coordinator delegates to Test Generation Agent
   - Generates targeted regression tests
   - Focuses on payment flow
   
2. Coordinator provides execution plan
   - 15 critical tests (30 minutes)
   - 25 high priority tests (60 minutes)
   - Recommendation: Run critical tests immediately

### Example 10: Performance Validation

**Input to QA Coordinator Agent**:
```
Validate performance improvements in version 2.8.0:

Release Notes: "Optimized database queries, improved caching"
Baseline: Version 2.7.0 metrics
Target: 30% improvement in response times
Scope: Performance testing only
```

**Workflow**:
1. Coordinator delegates to NFR Assessment Agent
   - Runs baseline comparison
   - Measures improvements
   
2. Coordinator provides report
   - Response time improved by 35% ✓
   - Throughput increased by 40% ✓
   - CPU usage reduced by 20% ✓
   - Recommendation: Performance targets met

## Tips for Effective Usage

### 1. Provide Clear Context
- Include all relevant documentation
- Specify the scope clearly
- Define success criteria
- Set priorities

### 2. Use the Right Agent
- **Test Generation**: When you need test cases
- **Exploratory Testing**: When you need issue discovery
- **NFR Assessment**: When you need performance data
- **QA Coordinator**: When you need comprehensive QA

### 3. Iterate and Refine
- Review initial results
- Provide feedback
- Request additional tests if needed
- Adjust scope based on findings

### 4. Integrate with CI/CD
- Export generated tests
- Add to test automation suite
- Run regression tests on every build
- Monitor performance trends

## Common Patterns

### Pattern 1: New Feature Development
```
1. Generate tests from requirements (Test Generation Agent)
2. Implement feature
3. Run generated tests
4. Perform exploratory testing (Exploratory Agent)
5. Fix discovered issues
6. Run performance baseline (NFR Agent)
```

### Pattern 2: Release Validation
```
1. Generate regression tests (Test Generation Agent)
2. Run regression suite
3. Perform exploratory testing on changed areas
4. Run performance comparison tests
5. Review consolidated findings (QA Coordinator)
6. Make go/no-go decision
```

### Pattern 3: Performance Optimization
```
1. Establish baseline (NFR Agent)
2. Implement optimizations
3. Run performance tests
4. Compare results
5. Iterate until targets met
```

## Troubleshooting

### Issue: Tests are too generic
**Solution**: Provide more detailed requirements and examples

### Issue: Too many tests generated
**Solution**: Specify priority levels and focus areas

### Issue: Missing edge cases
**Solution**: Use the generate_edge_cases tool explicitly

### Issue: Performance tests fail
**Solution**: Check test environment matches production specs

## Next Steps

1. Start with simple examples
2. Gradually increase complexity
3. Integrate into your workflow
4. Customize agents for your needs
5. Share findings with your team

For more information, see the main [README.md](README.md).