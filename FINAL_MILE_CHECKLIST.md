## Final Mile Checklist

This checklist enforces the American Circuits – Security Standards Protocol (v1.0). All items must pass before production release.

See: `SECURITY_STANDARDS_PROTOCOL.md` (alias: `security_standards.protocol.md`).

### 1) Cybersecurity Test
- [ ] Run SAST (TypeScript/JavaScript): `npm run lint` and consider `semgrep` if available
- [ ] Run dependency audit (Node): `npm audit --production`
- [ ] Run Python SAST if Python present: `bandit -r api` (optional)
- [ ] Python dependency audit: `safety check -r api/requirements.txt` (optional)
- [ ] Run secrets scan: `gitleaks detect --no-git -v` (optional)
- [ ] Verify OWASP Top 10 not present in basic flows (XSS, CSRF, SSRF, IDOR)
- [ ] Confirm secrets not in code, env, or logs

### 2) Quality Check
- [ ] Lint passes: `npm run lint`
- [ ] Type-check passes: `npm run type-check`
- [ ] Unit tests (if present) >= 80% coverage
- [ ] Error handling and logging meet standards

### 3) Performance Check
- [ ] Start stack: `docker-compose up -d`
- [ ] Run k6 perf test: `k6 run tests/perf/k6_health_check.js`
- [ ] p95 response time < 300ms, CPU < 70%, memory stable under load
- [ ] Validate scalability assumptions

### 4) Approvals
- [ ] Cybersecurity: PASS
- [ ] Quality: PASS
- [ ] Performance: PASS

Sign-off:
- Engineering Lead: ______________________  Date: __________
- Security Lead:    ______________________  Date: __________
- Product Owner:    ______________________  Date: __________


