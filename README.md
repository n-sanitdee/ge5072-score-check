# GE5072 Score Check

Students type their own code (S-XXXX) and see their GE5072/GE072 คะแนนเก็บ (อาจารย์ไทย, เต็ม 45),
Bonus Part A/B, and the topped-up total (max 45), using the method announced in Teams on 26 Nov 2026.

## Privacy

- `scores.enc.json` holds no names, no student IDs and no readable scores. Each student's row is
  encrypted (AES-256-GCM) with a key derived from that student's own code (PBKDF2-SHA256), and
  the row's lookup id is derived from the same code. The page decrypts one row in the browser;
  nothing is sent anywhere.
- Codes are only 4 characters, so this stops casual browsing, not a determined brute-force attempt.
  The data is the same pseudonymised extract students already see in the shared student-view file.
- `S-TEST` is a demo row with made-up numbers.

## Updating the scores

1. Make sure the pseudonymised extract is current (regenerate after editing the master):

       cd ~/Library/CloudStorage/OneDrive-UniversityoftheThaiChamberofCommerce/Pseudonymisation
       /opt/homebrew/bin/python3.11 ge5072_pseudonymise.py --if-changed

2. Rebuild and publish:

       cd ~/ge5072-score-check
       /opt/homebrew/bin/python3.11 build_scores.py --push

   GitHub Pages redeploys in about a minute. The build refuses to run if a new exercise column
   (Ex 12+) appears, because the Part A total (65) and the 26 Nov post would then be out of date.

A column that nobody has a non-zero mark in yet (Course Evaluation, Part B, today) shows as
"รอบันทึก" instead of 0, and is left out of the total until it is entered.
