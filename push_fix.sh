#!/bin/bash
# Run this once to push the bug fixes:
# chmod +x push_fix.sh && ./push_fix.sh

cd "$(dirname "$0")"
rm -f .git/index.lock
git add app.py
git commit -m "fix: white box, button crash, thumbnail truncation in Trends tab

- Remove broken st.markdown div wrapper (caused empty white rectangle at top)
- Make 'Test a Hypothesis' label larger (1.15rem bold)
- Fix text_input value= param crash (was navigating to home on every button click)
- Increase THUMB URL truncation 80->300 chars for TikTok/Instagram CDN URLs"
git push origin main
echo "Done!"
