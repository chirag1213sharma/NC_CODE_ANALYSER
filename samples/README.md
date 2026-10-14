# Sample NC Files

This directory contains sample NC code files for testing the NC Code Analyser.

## Files

### Progression Example

- `baseline_sample.nc` - Original NC program
- `new_sample.nc` - Optimized version with improved feeds/speeds and an added chamfer operation

Changes in new version:

- Increased spindle speeds for better surface finish
- Increased feed rates for faster cycle time
- Added new Operation 5: Chamfer Holes

**Expected Classification: PROGRESSION**

### Regression Example

- `regression_baseline.nc` - Working NC program with center drill, drill, and tap operations
- `regression_new.nc` - Broken version with coordinate errors and missing tap operation

Problems in new version:

- Drill holes are offset by 5mm (X55, Y55 instead of X50, Y50)
- Tapping operation is completely missing
- This would result in scrapped parts!

**Expected Classification: REGRESSION**

## How to Test

1. Start the NC Code Analyser server:

   ```bash
   python -m uvicorn src.main:app --reload
   ```

2. Open http://localhost:8000 in your browser

3. Upload the baseline and new files to see the analysis

4. Compare the AI classification with the expected result

5. Submit feedback if the AI classification needs correction
