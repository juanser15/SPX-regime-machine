# Regime Outlook — RESEARCH / SHADOW

**NOT VALIDATED / NOT FOR PORTFOLIO ACTION.** No top-card action, classifier threshold, or live forecast is changed.

## Data contract and predeclared gate
Yahoo historical daily closes were retrieved in one later snapshot. Frozen-v1 features and states use only observations dated <= t, but past Yahoo vintages are NOT available. These are date-ordered retrospective OOS research replays, NOT historical live predictions or deployable probabilities.

Frozen v1 reconstruction: 4,150 rows, 2010-03-30–2026-09-24; marked RESEARCH RECONSTRUCTION. Prefix invariance on actual Yahoo data: 800, 1600, 2600, 3600 rows, zero changes to past states/scores.

Origins use only the two predeclared causal scores and current state at t. Targets are the frozen classifier's state exactly h observed trading sessions later, not SPX returns. Gaps in SPX observations invalidate a pair. The origin's recorded availability is the maximum of close+6h, Yahoo retrieval, and reconstruction calculation. Because historical rows were obtained in the later Yahoo snapshot, **this cannot certify a forecast was available at its original historical date**.

Expanding 1,260-session initial training window, 252-session test blocks, and horizon-sized embargo *after the last training label*. Models and thresholds were declared before inspecting results: persistence, unconditional frequencies, direct state-conditional empirical Markov, and fixed-L2 multinomial logistic on current state plus body and overall stress. No search or crisis-era tuning. These rules are fixed in this implementation but were not independently preregistered; interpret the quantitative comparisons as exploratory. A hidden-state challenger was not run: a fair identifiable point-in-time comparison cannot be established from these historical source vintages.

Calibration gate: For every destination: >=50 positives, every populated one-of-five fixed-width score bins >=30 observations, ECE <=0.05 and max bin gap <=0.10.
Promotion requires: >=1500 common OOS origins, >=6 test blocks, >=50 distinct one-step entries per destination; Log loss AND multiclass Brier >=1% better than BOTH persistence and state-conditional Markov on identical rows; dual-metric wins in >=2/3 of annual blocks and positive gains in all three chronological thirds.; archived, dated Yahoo vintages available BEFORE each forecast origin.
The persistence benchmark remains exactly one-hot; only its log-loss evaluation clips to 1e-6. No raw transition score is promoted to a production probability. Overlapping h-day targets are reported with distinct one-step transition counts and fold/era checks, not treated as independent events.

## 1 trading day: INSUFFICIENT EVIDENCE
Historical Yahoo source vintages were not captured at each session: real-time point-in-time availability cannot be certified. Quantitative gates alone cannot override the provenance gate.
Common chronological OOS origins: 2,944 (2015-01-06–2026-09-23); 12 test blocks. Distinct adjacent state changes: 587 (destination entries: {'RISK-ON': 164, 'NEUTRAL': 292, 'DE-RISK': 131}).
Origin classes: {'RISK-ON': 844, 'NEUTRAL': 1363, 'DE-RISK': 737}; destination classes: {'RISK-ON': 844, 'NEUTRAL': 1364, 'DE-RISK': 736}. Observed h-step transition counts: {'RISK-ON': {'RISK-ON': 681, 'NEUTRAL': 159, 'DE-RISK': 4}, 'NEUTRAL': {'RISK-ON': 163, 'NEUTRAL': 1073, 'DE-RISK': 127}, 'DE-RISK': {'RISK-ON': 0, 'NEUTRAL': 132, 'DE-RISK': 605}}.
Sample gate: PASS; logistic quantitative gate: PASS; historical source-vintage gate: FAIL.

| Model | OOS log loss ↓ | Multiclass Brier ↓ | Mean max score | Calibration |
|---|---:|---:|---:|---|
| persistence | 2.7453 | 0.3974 | 1.000 | FAIL |
| unconditional | 1.0762 | 0.6488 | 0.471 | PASS |
| markov | 0.5756 | 0.3306 | 0.797 | PASS |
| logistic | 0.4710 | 0.2848 | 0.786 | PASS |

Pairwise gains versus common-row baselines (positive = lower log loss AND Brier):
- markov vs persistence: log-loss +79.03%, Brier +16.81%; 11/12 blocks win both; chronological third deltas (log loss / Brier): early +2.2559/+0.0721; middle +2.1227/+0.0650; late +2.1303/+0.0634.
- logistic vs persistence: log-loss +82.84%, Brier +28.33%; 12/12 blocks win both; chronological third deltas (log loss / Brier): early +2.3584/+0.1197; middle +2.2258/+0.1079; late +2.2385/+0.1101.
- logistic vs markov: log-loss +18.17%, Brier +13.84%; 12/12 blocks win both; chronological third deltas (log loss / Brier): early +0.1025/+0.0476; middle +0.1031/+0.0430; late +0.1082/+0.0467.

Classwise reliability (fixed 0.2-wide score bins; each bin lists n / mean score / observed destination rate):
- **persistence:**
  - RISK-ON (844 positives): ECE 0.111, max gap 0.193; 0.0–0.2: 2100 / 0.000 / 0.078; 0.8–1.0: 844 / 1.000 / 0.807.
  - NEUTRAL (1364 positives): ECE 0.197, max gap 0.213; 0.0–0.2: 1581 / 0.000 / 0.184; 0.8–1.0: 1363 / 1.000 / 0.787.
  - DE-RISK (736 positives): ECE 0.089, max gap 0.179; 0.0–0.2: 2207 / 0.000 / 0.059; 0.8–1.0: 737 / 1.000 / 0.821.
- **unconditional:**
  - RISK-ON (844 positives): ECE 0.017, max gap 0.017; 0.2–0.4: 2944 / 0.303 / 0.287.
  - NEUTRAL (1364 positives): ECE 0.008, max gap 0.008; 0.4–0.6: 2944 / 0.471 / 0.463.
  - DE-RISK (736 positives): ECE 0.025, max gap 0.025; 0.2–0.4: 2944 / 0.225 / 0.250.
- **markov:**
  - RISK-ON (844 positives): ECE 0.015, max gap 0.048; 0.0–0.2: 2100 / 0.085 / 0.078; 0.6–0.8: 669 / 0.789 / 0.819; 0.8–1.0: 175 / 0.808 / 0.760.
  - NEUTRAL (1364 positives): ECE 0.020, max gap 0.071; 0.0–0.2: 1090 / 0.185 / 0.206; 0.2–0.4: 491 / 0.207 / 0.136; 0.6–0.8: 1363 / 0.787 / 0.787.
  - DE-RISK (736 positives): ECE 0.006, max gap 0.007; 0.0–0.2: 2207 / 0.053 / 0.059; 0.8–1.0: 737 / 0.818 / 0.821.
- **logistic:**
  - RISK-ON (844 positives): ECE 0.024, max gap 0.044; 0.0–0.2: 1726 / 0.041 / 0.022; 0.2–0.4: 344 / 0.284 / 0.328; 0.4–0.6: 67 / 0.502 / 0.463; 0.6–0.8: 353 / 0.718 / 0.705; 0.8–1.0: 454 / 0.877 / 0.910.
  - NEUTRAL (1364 positives): ECE 0.040, max gap 0.058; 0.0–0.2: 869 / 0.116 / 0.058; 0.2–0.4: 617 / 0.282 / 0.314; 0.4–0.6: 131 / 0.473 / 0.511; 0.6–0.8: 646 / 0.725 / 0.704; 0.8–1.0: 681 / 0.834 / 0.878.
  - DE-RISK (736 positives): ECE 0.023, max gap 0.089; 0.0–0.2: 2029 / 0.043 / 0.037; 0.2–0.4: 177 / 0.256 / 0.305; 0.4–0.6: 81 / 0.549 / 0.481; 0.6–0.8: 261 / 0.714 / 0.682; 0.8–1.0: 396 / 0.894 / 0.982.

Secondary diagnostics: confusion matrices (actual rows → predicted columns) and score sharpness (destination score standard deviations):
- persistence: confusion {'RISK-ON': {'RISK-ON': 681, 'NEUTRAL': 163, 'DE-RISK': 0}, 'NEUTRAL': {'RISK-ON': 159, 'NEUTRAL': 1073, 'DE-RISK': 132}, 'DE-RISK': {'RISK-ON': 4, 'NEUTRAL': 127, 'DE-RISK': 605}}; sharpness {'RISK-ON': 0.4522130228435495, 'NEUTRAL': 0.498627305328609, 'DE-RISK': 0.4332086351611133}.
- unconditional: confusion {'RISK-ON': {'RISK-ON': 0, 'NEUTRAL': 844, 'DE-RISK': 0}, 'NEUTRAL': {'RISK-ON': 0, 'NEUTRAL': 1364, 'DE-RISK': 0}, 'DE-RISK': {'RISK-ON': 0, 'NEUTRAL': 736, 'DE-RISK': 0}}; sharpness {'RISK-ON': 0.013973635153320329, 'NEUTRAL': 0.0064061048968864455, 'DE-RISK': 0.011555606682073354}.
- markov: confusion {'RISK-ON': {'RISK-ON': 681, 'NEUTRAL': 163, 'DE-RISK': 0}, 'NEUTRAL': {'RISK-ON': 159, 'NEUTRAL': 1073, 'DE-RISK': 132}, 'DE-RISK': {'RISK-ON': 4, 'NEUTRAL': 127, 'DE-RISK': 605}}; sharpness {'RISK-ON': 0.3245593271817206, 'NEUTRAL': 0.2967482436904751, 'DE-RISK': 0.33327491610740867}.
- logistic: confusion {'RISK-ON': {'RISK-ON': 681, 'NEUTRAL': 163, 'DE-RISK': 0}, 'NEUTRAL': {'RISK-ON': 159, 'NEUTRAL': 1076, 'DE-RISK': 129}, 'DE-RISK': {'RISK-ON': 4, 'NEUTRAL': 128, 'DE-RISK': 604}}; sharpness {'RISK-ON': 0.3392779814767763, 'NEUTRAL': 0.30260163092008996, 'DE-RISK': 0.3307298044889677}.

DE-RISK entry lead behavior on *distinct* entry dates with matching 1/3/5-session OOS scores (not a trade alarm):
- markov: matched entries 129; median matched DE-RISK score at −5/−3/−1: {'minus_1': 0.08138101109741061, 'minus_3': 0.14417344173441735, 'minus_5': 0.1606022584692597}; 1D rising-score non-DE-RISK origins without DE-RISK destination: 157/160; 1D false alarms at >=0.50 from a non-DE-RISK origin: 0/0 (fraction None).
- logistic: matched entries 129; median matched DE-RISK score at −5/−3/−1: {'minus_1': 0.18219264687661946, 'minus_3': 0.25122106158065927, 'minus_5': 0.21822678306077134}; 1D rising-score non-DE-RISK origins without DE-RISK destination: 903/962; 1D false alarms at >=0.50 from a non-DE-RISK origin: 0/0 (fraction None).

Last training fold's regularized logit coefficients (RISK-ON/NEUTRAL relative to DE-RISK; descriptive, not production parameters):
```json
{
  "destination_logits_vs_DE-RISK": {
    "NEUTRAL": {
      "body_stress_score_per_train_sd": -1.0222545296630339,
      "current_NEUTRAL": 1.0182038230667805,
      "current_RISK-ON": -0.017953093612166855,
      "intercept": 1.6200850423319098,
      "overall_stress_score_per_train_sd": -1.3491339431632352
    },
    "RISK-ON": {
      "body_stress_score_per_train_sd": -2.2979395695697185,
      "current_NEUTRAL": 0.1944699671379634,
      "current_RISK-ON": -0.0535966863347488,
      "intercept": -0.09357451261772307,
      "overall_stress_score_per_train_sd": -3.163538273938656
    }
  },
  "features": [
    "intercept",
    "current_RISK-ON",
    "current_NEUTRAL",
    "body_stress_score_per_train_sd",
    "overall_stress_score_per_train_sd"
  ],
  "l2_strength": 10.0,
  "train_factor_means": {
    "body_stress_score": 48.72473008047755,
    "overall_stress_score": 49.28991628712741
  },
  "train_factor_scales": {
    "body_stress_score": 23.147593198684824,
    "overall_stress_score": 20.031945198981592
  }
}
```

## 3 trading days: INSUFFICIENT EVIDENCE
Historical Yahoo source vintages were not captured at each session: real-time point-in-time availability cannot be certified. Quantitative logistic gates also fail.
Common chronological OOS origins: 2,938 (2015-01-06–2026-09-21); 12 test blocks. Distinct adjacent state changes: 587 (destination entries: {'RISK-ON': 164, 'NEUTRAL': 292, 'DE-RISK': 131}).
Origin classes: {'RISK-ON': 841, 'NEUTRAL': 1360, 'DE-RISK': 737}; destination classes: {'RISK-ON': 842, 'NEUTRAL': 1364, 'DE-RISK': 732}. Observed h-step transition counts: {'RISK-ON': {'RISK-ON': 568, 'NEUTRAL': 258, 'DE-RISK': 15}, 'NEUTRAL': {'RISK-ON': 269, 'NEUTRAL': 889, 'DE-RISK': 202}, 'DE-RISK': {'RISK-ON': 5, 'NEUTRAL': 217, 'DE-RISK': 515}}.
Sample gate: PASS; logistic quantitative gate: FAIL; historical source-vintage gate: FAIL.

| Model | OOS log loss ↓ | Multiclass Brier ↓ | Mean max score | Calibration |
|---|---:|---:|---:|---|
| persistence | 4.5425 | 0.6576 | 1.000 | FAIL |
| unconditional | 1.0756 | 0.6484 | 0.472 | PASS |
| markov | 0.7760 | 0.4760 | 0.661 | PASS |
| logistic | 0.6980 | 0.4309 | 0.660 | FAIL |

Pairwise gains versus common-row baselines (positive = lower log loss AND Brier):
- markov vs persistence: log-loss +82.92%, Brier +27.61%; 12/12 blocks win both; chronological third deltas (log loss / Brier): early +3.9592/+0.1989; middle +3.7051/+0.1768; late +3.6351/+0.1690.
- logistic vs persistence: log-loss +84.63%, Brier +34.48%; 12/12 blocks win both; chronological third deltas (log loss / Brier): early +4.0334/+0.2455; middle +3.7878/+0.2205; late +3.7122/+0.2142.
- logistic vs markov: log-loss +10.05%, Brier +9.48%; 12/12 blocks win both; chronological third deltas (log loss / Brier): early +0.0742/+0.0465; middle +0.0826/+0.0437; late +0.0771/+0.0452.

Classwise reliability (fixed 0.2-wide score bins; each bin lists n / mean score / observed destination rate):
- **persistence:**
  - RISK-ON (842 positives): ECE 0.186, max gap 0.325; 0.0–0.2: 2097 / 0.000 / 0.131; 0.8–1.0: 841 / 1.000 / 0.675.
  - NEUTRAL (1364 positives): ECE 0.322, max gap 0.346; 0.0–0.2: 1578 / 0.000 / 0.301; 0.8–1.0: 1360 / 1.000 / 0.654.
  - DE-RISK (732 positives): ECE 0.149, max gap 0.301; 0.0–0.2: 2201 / 0.000 / 0.099; 0.8–1.0: 737 / 1.000 / 0.699.
- **unconditional:**
  - RISK-ON (842 positives): ECE 0.016, max gap 0.016; 0.2–0.4: 2938 / 0.303 / 0.287.
  - NEUTRAL (1364 positives): ECE 0.008, max gap 0.008; 0.4–0.6: 2938 / 0.472 / 0.464.
  - DE-RISK (732 positives): ECE 0.024, max gap 0.024; 0.2–0.4: 2938 / 0.225 / 0.249.
- **markov:**
  - RISK-ON (842 positives): ECE 0.017, max gap 0.024; 0.0–0.2: 917 / 0.045 / 0.061; 0.2–0.4: 1180 / 0.209 / 0.185; 0.6–0.8: 841 / 0.667 / 0.675.
  - NEUTRAL (1364 positives): ECE 0.010, max gap 0.016; 0.2–0.4: 1578 / 0.317 / 0.301; 0.6–0.8: 1360 / 0.651 / 0.654.
  - DE-RISK (732 positives): ECE 0.009, max gap 0.025; 0.0–0.2: 2201 / 0.095 / 0.099; 0.6–0.8: 737 / 0.674 / 0.699.
- **logistic:**
  - RISK-ON (842 positives): ECE 0.017, max gap 0.089; 0.0–0.2: 1463 / 0.059 / 0.044; 0.2–0.4: 507 / 0.294 / 0.314; 0.4–0.6: 351 / 0.505 / 0.476; 0.6–0.8: 523 / 0.697 / 0.698; 0.8–1.0: 94 / 0.826 / 0.915.
  - NEUTRAL (1364 positives): ECE 0.024, max gap 0.102; 0.0–0.2: 251 / 0.162 / 0.060; 0.2–0.4: 927 / 0.301 / 0.280; 0.4–0.6: 669 / 0.496 / 0.514; 0.6–0.8: 1091 / 0.671 / 0.683.
  - DE-RISK (732 positives): ECE 0.027, max gap 0.124; 0.0–0.2: 1802 / 0.057 / 0.054; 0.2–0.4: 391 / 0.274 / 0.307; 0.4–0.6: 271 / 0.509 / 0.443; 0.6–0.8: 334 / 0.701 / 0.775; 0.8–1.0: 140 / 0.847 / 0.971.

Secondary diagnostics: confusion matrices (actual rows → predicted columns) and score sharpness (destination score standard deviations):
- persistence: confusion {'RISK-ON': {'RISK-ON': 568, 'NEUTRAL': 269, 'DE-RISK': 5}, 'NEUTRAL': {'RISK-ON': 258, 'NEUTRAL': 889, 'DE-RISK': 217}, 'DE-RISK': {'RISK-ON': 15, 'NEUTRAL': 202, 'DE-RISK': 515}}; sharpness {'RISK-ON': 0.4520072717682832, 'NEUTRAL': 0.49862168519724476, 'DE-RISK': 0.4335028666953935}.
- unconditional: confusion {'RISK-ON': {'RISK-ON': 0, 'NEUTRAL': 842, 'DE-RISK': 0}, 'NEUTRAL': {'RISK-ON': 0, 'NEUTRAL': 1364, 'DE-RISK': 0}, 'DE-RISK': {'RISK-ON': 0, 'NEUTRAL': 732, 'DE-RISK': 0}}; sharpness {'RISK-ON': 0.013863721140064051, 'NEUTRAL': 0.006440927286762408, 'DE-RISK': 0.011592929990018272}.
- markov: confusion {'RISK-ON': {'RISK-ON': 568, 'NEUTRAL': 269, 'DE-RISK': 5}, 'NEUTRAL': {'RISK-ON': 258, 'NEUTRAL': 889, 'DE-RISK': 217}, 'DE-RISK': {'RISK-ON': 15, 'NEUTRAL': 202, 'DE-RISK': 515}}; sharpness {'RISK-ON': 0.2527499353993879, 'NEUTRAL': 0.16684213647633436, 'DE-RISK': 0.25648142225176335}.
- logistic: confusion {'RISK-ON': {'RISK-ON': 561, 'NEUTRAL': 278, 'DE-RISK': 3}, 'NEUTRAL': {'RISK-ON': 255, 'NEUTRAL': 951, 'DE-RISK': 158}, 'DE-RISK': {'RISK-ON': 15, 'NEUTRAL': 238, 'DE-RISK': 479}}; sharpness {'RISK-ON': 0.2722590776721535, 'NEUTRAL': 0.18603019692220796, 'DE-RISK': 0.26802843721844255}.

DE-RISK entry lead behavior on *distinct* entry dates with matching 1/3/5-session OOS scores (not a trade alarm):
- markov: matched entries 129; median matched DE-RISK score at −5/−3/−1: {'minus_1': 0.08138101109741061, 'minus_3': 0.14417344173441735, 'minus_5': 0.1606022584692597}; 3D rising-score non-DE-RISK origins without DE-RISK destination: 148/158; 3D false alarms at >=0.50 from a non-DE-RISK origin: 0/0 (fraction None).
- logistic: matched entries 129; median matched DE-RISK score at −5/−3/−1: {'minus_1': 0.18219264687661946, 'minus_3': 0.25122106158065927, 'minus_5': 0.21822678306077134}; 3D rising-score non-DE-RISK origins without DE-RISK destination: 841/946; 3D false alarms at >=0.50 from a non-DE-RISK origin: 0/0 (fraction None).

Last training fold's regularized logit coefficients (RISK-ON/NEUTRAL relative to DE-RISK; descriptive, not production parameters):
```json
{
  "destination_logits_vs_DE-RISK": {
    "NEUTRAL": {
      "body_stress_score_per_train_sd": -0.46196260172151354,
      "current_NEUTRAL": 0.2291555737329546,
      "current_RISK-ON": -0.22472020781519325,
      "intercept": 1.5343140551118526,
      "overall_stress_score_per_train_sd": -1.2577599473876988
    },
    "RISK-ON": {
      "body_stress_score_per_train_sd": -1.6279453965850568,
      "current_NEUTRAL": 0.24267160369732962,
      "current_RISK-ON": 0.031684467455254814,
      "intercept": 0.051259944303285246,
      "overall_stress_score_per_train_sd": -1.9988448599665734
    }
  },
  "features": [
    "intercept",
    "current_RISK-ON",
    "current_NEUTRAL",
    "body_stress_score_per_train_sd",
    "overall_stress_score_per_train_sd"
  ],
  "l2_strength": 10.0,
  "train_factor_means": {
    "body_stress_score": 48.74072966426715,
    "overall_stress_score": 49.30927914140678
  },
  "train_factor_scales": {
    "body_stress_score": 23.15352536690483,
    "overall_stress_score": 20.0324965521747
  }
}
```

## 5 trading days: INSUFFICIENT EVIDENCE
Historical Yahoo source vintages were not captured at each session: real-time point-in-time availability cannot be certified. Quantitative logistic gates also fail.
Common chronological OOS origins: 2,932 (2015-01-06–2026-09-17); 12 test blocks. Distinct adjacent state changes: 587 (destination entries: {'RISK-ON': 164, 'NEUTRAL': 292, 'DE-RISK': 131}).
Origin classes: {'RISK-ON': 840, 'NEUTRAL': 1355, 'DE-RISK': 737}; destination classes: {'RISK-ON': 840, 'NEUTRAL': 1363, 'DE-RISK': 729}. Observed h-step transition counts: {'RISK-ON': {'RISK-ON': 500, 'NEUTRAL': 304, 'DE-RISK': 36}, 'NEUTRAL': {'RISK-ON': 321, 'NEUTRAL': 803, 'DE-RISK': 231}, 'DE-RISK': {'RISK-ON': 19, 'NEUTRAL': 256, 'DE-RISK': 462}}.
Sample gate: PASS; logistic quantitative gate: FAIL; historical source-vintage gate: FAIL.

| Model | OOS log loss ↓ | Multiclass Brier ↓ | Mean max score | Calibration |
|---|---:|---:|---:|---|
| persistence | 5.4989 | 0.7960 | 1.000 | FAIL |
| unconditional | 1.0751 | 0.6481 | 0.472 | PASS |
| markov | 0.8706 | 0.5348 | 0.591 | FAIL |
| logistic | 0.8154 | 0.5012 | 0.594 | FAIL |

Pairwise gains versus common-row baselines (positive = lower log loss AND Brier):
- markov vs persistence: log-loss +84.17%, Brier +32.82%; 12/12 blocks win both; chronological third deltas (log loss / Brier): early +4.6789/+0.2638; middle +4.7976/+0.2816; late +4.4084/+0.2384.
- logistic vs persistence: log-loss +85.17%, Brier +37.04%; 12/12 blocks win both; chronological third deltas (log loss / Brier): early +4.7264/+0.2960; middle +4.8667/+0.3211; late +4.4572/+0.2674.
- logistic vs markov: log-loss +6.34%, Brier +6.28%; 12/12 blocks win both; chronological third deltas (log loss / Brier): early +0.0475/+0.0322; middle +0.0691/+0.0395; late +0.0488/+0.0290.

Classwise reliability (fixed 0.2-wide score bins; each bin lists n / mean score / observed destination rate):
- **persistence:**
  - RISK-ON (840 positives): ECE 0.232, max gap 0.405; 0.0–0.2: 2092 / 0.000 / 0.163; 0.8–1.0: 840 / 1.000 / 0.595.
  - NEUTRAL (1363 positives): ECE 0.379, max gap 0.407; 0.0–0.2: 1577 / 0.000 / 0.355; 0.8–1.0: 1355 / 1.000 / 0.593.
  - DE-RISK (729 positives): ECE 0.185, max gap 0.373; 0.0–0.2: 2195 / 0.000 / 0.122; 0.8–1.0: 737 / 1.000 / 0.627.
- **unconditional:**
  - RISK-ON (840 positives): ECE 0.016, max gap 0.016; 0.2–0.4: 2932 / 0.302 / 0.286.
  - NEUTRAL (1363 positives): ECE 0.007, max gap 0.007; 0.4–0.6: 2932 / 0.472 / 0.465.
  - DE-RISK (729 positives): ECE 0.023, max gap 0.023; 0.2–0.4: 2932 / 0.225 / 0.249.
- **markov:**
  - RISK-ON (840 positives): ECE 0.028, max gap 0.102; 0.0–0.2: 737 / 0.033 / 0.026; 0.2–0.4: 1355 / 0.244 / 0.237; 0.4–0.6: 535 / 0.580 / 0.647; 0.6–0.8: 305 / 0.607 / 0.505.
  - NEUTRAL (1363 positives): ECE 0.014, max gap 0.085; 0.2–0.4: 1487 / 0.367 / 0.358; 0.4–0.6: 1227 / 0.577 / 0.585; 0.6–0.8: 218 / 0.603 / 0.518.
  - DE-RISK (729 positives): ECE 0.026, max gap 0.113; 0.0–0.2: 2195 / 0.119 / 0.122; 0.4–0.6: 436 / 0.575 / 0.688; 0.6–0.8: 301 / 0.611 / 0.538.
- **logistic:**
  - RISK-ON (840 positives): ECE 0.025, max gap 0.037; 0.0–0.2: 1292 / 0.078 / 0.058; 0.2–0.4: 674 / 0.296 / 0.334; 0.4–0.6: 568 / 0.508 / 0.477; 0.6–0.8: 398 / 0.668 / 0.676.
  - NEUTRAL (1363 positives): ECE 0.027, max gap 0.180; 0.0–0.2: 25 / 0.180 / 0.000; 0.2–0.4: 935 / 0.323 / 0.275; 0.4–0.6: 1326 / 0.511 / 0.532; 0.6–0.8: 646 / 0.624 / 0.621.
  - DE-RISK (729 positives): ECE 0.021, max gap 0.181; 0.0–0.2: 1739 / 0.080 / 0.081; 0.2–0.4: 479 / 0.275 / 0.284; 0.4–0.6: 387 / 0.500 / 0.470; 0.6–0.8: 306 / 0.684 / 0.817; 0.8–1.0: 21 / 0.819 / 1.000.

Secondary diagnostics: confusion matrices (actual rows → predicted columns) and score sharpness (destination score standard deviations):
- persistence: confusion {'RISK-ON': {'RISK-ON': 500, 'NEUTRAL': 321, 'DE-RISK': 19}, 'NEUTRAL': {'RISK-ON': 304, 'NEUTRAL': 803, 'DE-RISK': 256}, 'DE-RISK': {'RISK-ON': 36, 'NEUTRAL': 231, 'DE-RISK': 462}}; sharpness {'RISK-ON': 0.4521229130927607, 'NEUTRAL': 0.49856470287468857, 'DE-RISK': 0.433797495433486}.
- unconditional: confusion {'RISK-ON': {'RISK-ON': 0, 'NEUTRAL': 840, 'DE-RISK': 0}, 'NEUTRAL': {'RISK-ON': 0, 'NEUTRAL': 1363, 'DE-RISK': 0}, 'DE-RISK': {'RISK-ON': 0, 'NEUTRAL': 729, 'DE-RISK': 0}}; sharpness {'RISK-ON': 0.013810832385121895, 'NEUTRAL': 0.006372644457650418, 'DE-RISK': 0.011395731536056206}.
- markov: confusion {'RISK-ON': {'RISK-ON': 500, 'NEUTRAL': 321, 'DE-RISK': 19}, 'NEUTRAL': {'RISK-ON': 304, 'NEUTRAL': 803, 'DE-RISK': 256}, 'DE-RISK': {'RISK-ON': 36, 'NEUTRAL': 231, 'DE-RISK': 462}}; sharpness {'RISK-ON': 0.2082440148773989, 'NEUTRAL': 0.11238671476714303, 'DE-RISK': 0.21027072851986806}.
- logistic: confusion {'RISK-ON': {'RISK-ON': 485, 'NEUTRAL': 344, 'DE-RISK': 11}, 'NEUTRAL': {'RISK-ON': 288, 'NEUTRAL': 908, 'DE-RISK': 167}, 'DE-RISK': {'RISK-ON': 35, 'NEUTRAL': 289, 'DE-RISK': 405}}; sharpness {'RISK-ON': 0.2268757694069969, 'NEUTRAL': 0.12720654723020683, 'DE-RISK': 0.22287536541404226}.

DE-RISK entry lead behavior on *distinct* entry dates with matching 1/3/5-session OOS scores (not a trade alarm):
- markov: matched entries 129; median matched DE-RISK score at −5/−3/−1: {'minus_1': 0.08138101109741061, 'minus_3': 0.14417344173441735, 'minus_5': 0.1606022584692597}; 5D rising-score non-DE-RISK origins without DE-RISK destination: 145/158; 5D false alarms at >=0.50 from a non-DE-RISK origin: 0/0 (fraction None).
- logistic: matched entries 129; median matched DE-RISK score at −5/−3/−1: {'minus_1': 0.18219264687661946, 'minus_3': 0.25122106158065927, 'minus_5': 0.21822678306077134}; 5D rising-score non-DE-RISK origins without DE-RISK destination: 850/959; 5D false alarms at >=0.50 from a non-DE-RISK origin: 0/0 (fraction None).

Last training fold's regularized logit coefficients (RISK-ON/NEUTRAL relative to DE-RISK; descriptive, not production parameters):
```json
{
  "destination_logits_vs_DE-RISK": {
    "NEUTRAL": {
      "body_stress_score_per_train_sd": -0.24137769863940117,
      "current_NEUTRAL": 0.19950717478776772,
      "current_RISK-ON": -0.2513264143775662,
      "intercept": 1.212420772424141,
      "overall_stress_score_per_train_sd": -1.0147130095086707
    },
    "RISK-ON": {
      "body_stress_score_per_train_sd": -1.3369364089574525,
      "current_NEUTRAL": 0.16626605427010016,
      "current_RISK-ON": -0.15593671435273682,
      "intercept": 0.18694149576073252,
      "overall_stress_score_per_train_sd": -1.272104278993094
    }
  },
  "features": [
    "intercept",
    "current_RISK-ON",
    "current_NEUTRAL",
    "body_stress_score_per_train_sd",
    "overall_stress_score_per_train_sd"
  ],
  "l2_strength": 10.0,
  "train_factor_means": {
    "body_stress_score": 48.75260604409562,
    "overall_stress_score": 49.325995026613334
  },
  "train_factor_scales": {
    "body_stress_score": 23.161872966163433,
    "overall_stress_score": 20.035404932729037
  }
}
```

## Decision
**INSUFFICIENT EVIDENCE at 1D, 3D, and 5D.** No model is selected or promoted. The frozen current-state PM action remains authoritative. No Signal Hub connection, actionable outlook, or new source was added.
