# Transition Hazard Gate — RESEARCH / SHADOW

**NOT VALIDATED / NOT FOR PORTFOLIO ACTION.** No change to frozen v1 or PM action.

Frozen causal date-prefix reconstruction from real persisted Yahoo closes; historical vendor vintages were retrieved later. Retrospective chronological OOS, NOT an executable historical point-in-time forecast.

## Fixed protocol
{
  "registration": "Fixed in code; no independently dated preregistration. Exploratory.",
  "targets": {
    "de_risk_entry": "non-DE-RISK origins; first DE-RISK observation in next h sessions",
    "any_transition": "all three origin states; S_(t+h) != S_t (endpoint, not any temporary round-trip)",
    "de_risk_exit": "DE-RISK origins; first non-DE-RISK observation in next h sessions"
  },
  "features": [
    "current state",
    "log1p(current run duration)",
    "body_stress_score at t",
    "overall_stress_score at t"
  ],
  "models": [
    "train-only Jeffreys-smoothed unconditional event rate",
    "fixed-L2 state/duration logistic",
    "same fixed-L2 logistic plus two market scores"
  ],
  "l2": 10,
  "initial_train_sessions": 1260,
  "test_block_sessions": 252,
  "purge": "last training label index < first test origin index - h",
  "operating_threshold": "fold-specific 90th percentile of fitted training scores; OOS untouched",
  "gate": ">=1000 OOS origins, >=100 positive labels, >=500 negatives, >=50 distinct events, >=6 folds; >=1% lower BOTH log loss and Brier than BOTH baselines; >=2/3 dual-metric fold wins vs duration, positive gains in all thirds; five fixed-width bins each populated >=30, ECE <=0.05, max gap <=0.10. Entry additionally needs alert recall >=0.25, precision >=2x base rate and false-positive rate <=0.15. No PASS without historical source vintages.",
  "sensitivity": "Only DE-RISK entry; frozen cutoff alternatives 30/70 and 40/60, not selected or tuned."
}

The 35/65 classifier cutoffs remain unchanged. Historical vintage availability fails every horizon's production evidence gate. Unconditional and duration-aware hazards are the baselines, not one-hot persistence. The market increment over duration is the primary comparison. Correlation between market features and the classifier-derived destination can create pseudo-predictability; this is a classifier-transition study, NOT an SPX-return forecast.

## OOS transition hazards

### de_risk_entry

#### 1 sessions — INSUFFICIENT EVIDENCE
Retrospective quantitative checks pass, but pre-origin Yahoo vintages do not exist; live point-in-time evidence is insufficient.
Common OOS origins 2,207 (2015-02-04–2026-09-23); 12 blocks; event labels 131, non-events 2,076; distinct event dates 131; base rate 5.94%. Origin states: {'NEUTRAL': 1363, 'RISK-ON': 844}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.2269 | 0.0560 | 0.0454 | 0.3773 | 0.0067 | 0.0067 | PASS |
| state_duration | 0.2053 | 0.0540 | 0.1118 | 0.7264 | 0.0067 | 0.0067 | PASS |
| market | 0.1681 | 0.0476 | 0.2815 | 0.8707 | 0.0066 | 0.0340 | PASS |
- Market vs unconditional: relative LL gain +25.92%, Brier gain +15.01%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0566/+0.0078; middle +0.0553/+0.0079; late +0.0645/+0.0095
- Market vs state_duration: relative LL gain +18.12%, Brier gain +11.89%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0380/+0.0061; middle +0.0363/+0.0061; late +0.0373/+0.0070
Fixed train-only top-decile operating point: {"alerts": 252, "base_event_rate": 0.05935659265971908, "false_alarms": 172, "false_positive_rate": 0.08285163776493257, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.31746031746031744, "precision_lift": 5.3483581727856535, "recall": 0.6106870229007634, "true_alarms": 80}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 2207, "mean_score": 0.052633005970709947, "event_rate": 0.05935659265971908}, {"bin": "0.2\u20130.4", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 2207, "mean_score": 0.05268364990447473, "event_rate": 0.05935659265971908}, {"bin": "0.2\u20130.4", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 2056, "mean_score": 0.03817231427715529, "event_rate": 0.042801556420233464}, {"bin": "0.2\u20130.4", "n": 151, "mean_score": 0.2507790935398717, "event_rate": 0.2847682119205298}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}]}
Entry lead diagnostic (all individual events in CSV): {"distinct_entries_in_oos_range": 131, "entries_elevated_before_event": 80, "lead_csv": "de_risk_entry_leads.csv", "matched_event_origins": 131, "median_first_elevated_lead_sessions": 1.0, "median_score_by_lag": {"minus_1": 0.18031140435281096, "minus_2": 0.12351720293224916, "minus_3": 0.07286108212650015, "minus_4": 0.05457307690291599, "minus_5": 0.03486166474919228}}
Sample gate True; operating gate True; sensitivity gate True; quantitative gate True.

#### 3 sessions — INSUFFICIENT EVIDENCE
Retrospective quantitative checks pass, but pre-origin Yahoo vintages do not exist; live point-in-time evidence is insufficient.
Common OOS origins 2,201 (2015-02-04–2026-09-21); 12 blocks; event labels 304, non-events 1,897; distinct event dates 131; base rate 13.81%. Origin states: {'NEUTRAL': 1360, 'RISK-ON': 841}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.4046 | 0.1197 | 0.1031 | 0.3528 | 0.0099 | 0.0099 | PASS |
| state_duration | 0.3600 | 0.1107 | 0.2337 | 0.7160 | 0.0090 | 0.0299 | PASS |
| market | 0.3112 | 0.0946 | 0.4433 | 0.8293 | 0.0109 | 0.0677 | PASS |
- Market vs unconditional: relative LL gain +23.08%, Brier gain +21.02%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0809/+0.0216; middle +0.0955/+0.0257; late +0.1038/+0.0281
- Market vs state_duration: relative LL gain +13.56%, Brier gain +14.57%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0462/+0.0147; middle +0.0552/+0.0175; late +0.0450/+0.0162
Fixed train-only top-decile operating point: {"alerts": 253, "base_event_rate": 0.13811903680145388, "false_alarms": 116, "false_positive_rate": 0.061149182920400634, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.541501976284585, "precision_lift": 3.9205455585604327, "recall": 0.4506578947368421, "true_alarms": 137}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 2201, "mean_score": 0.1282618861814384, "event_rate": 0.13811903680145388}, {"bin": "0.2\u20130.4", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 1713, "mean_score": 0.10257670925068668, "event_rate": 0.10566258026853473}, {"bin": "0.2\u20130.4", "n": 488, "mean_score": 0.22212395596347173, "event_rate": 0.2520491803278688}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 1689, "mean_score": 0.06384491928386553, "event_rate": 0.06275902901124926}, {"bin": "0.2\u20130.4", "n": 361, "mean_score": 0.2964025327646767, "event_rate": 0.3296398891966759}, {"bin": "0.4\u20130.6", "n": 151, "mean_score": 0.45547232081390915, "event_rate": 0.5231788079470199}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}]}
Entry lead diagnostic (all individual events in CSV): {"distinct_entries_in_oos_range": 131, "entries_elevated_before_event": 63, "lead_csv": "de_risk_entry_leads.csv", "matched_event_origins": 93, "median_first_elevated_lead_sessions": 2.0, "median_score_by_lag": {"minus_1": 0.37125270568974844, "minus_2": 0.2868637965340321, "minus_3": 0.1851935491151191, "minus_4": 0.15020887023011179, "minus_5": 0.1162200479934659}}
Sample gate True; operating gate True; sensitivity gate True; quantitative gate True.

#### 5 sessions — FAIL
Quantitative/calibration/operating/robustness gate fails.
Common OOS origins 2,195 (2015-02-04–2026-09-17); 12 blocks; event labels 438, non-events 1,757; distinct event dates 131; base rate 19.95%. Origin states: {'NEUTRAL': 1355, 'RISK-ON': 840}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.5037 | 0.1610 | 0.1494 | 0.3413 | 0.0347 | 0.1339 | FAIL |
| state_duration | 0.4582 | 0.1479 | 0.3127 | 0.6925 | 0.0125 | 0.0182 | PASS |
| market | 0.4144 | 0.1304 | 0.4892 | 0.7796 | 0.0141 | 0.0843 | FAIL |
- Market vs unconditional: relative LL gain +17.73%, Brier gain +18.96%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0720/+0.0252; middle +0.0996/+0.0347; late +0.0963/+0.0317
- Market vs state_duration: relative LL gain +9.54%, Brier gain +11.78%; 11/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0396/+0.0158; middle +0.0566/+0.0220; late +0.0350/+0.0145
Fixed train-only top-decile operating point: {"alerts": 252, "base_event_rate": 0.19954441913439636, "false_alarms": 96, "false_positive_rate": 0.05463858850313034, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.6190476190476191, "precision_lift": 3.1023048488801916, "recall": 0.3561643835616438, "true_alarms": 156}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 1981, "mean_score": 0.18952675275899822, "event_rate": 0.21352852094901564}, {"bin": "0.2\u20130.4", "n": 214, "mean_score": 0.2040358744394619, "event_rate": 0.07009345794392523}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 973, "mean_score": 0.09376041020640036, "event_rate": 0.08838643371017471}, {"bin": "0.2\u20130.4", "n": 1222, "mean_score": 0.26986606437881316, "event_rate": 0.28805237315875615}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 1411, "mean_score": 0.09462385232200297, "event_rate": 0.09213323883770376}, {"bin": "0.2\u20130.4", "n": 482, "mean_score": 0.2868250803728331, "event_rate": 0.2821576763485477}, {"bin": "0.4\u20130.6", "n": 291, "mean_score": 0.4861770101925917, "event_rate": 0.570446735395189}, {"bin": "0.6\u20130.8", "n": 11, "mean_score": 0.6153445367536623, "event_rate": 0.5454545454545454}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}]}
Entry lead diagnostic (all individual events in CSV): {"distinct_entries_in_oos_range": 131, "entries_elevated_before_event": 64, "lead_csv": "de_risk_entry_leads.csv", "matched_event_origins": 89, "median_first_elevated_lead_sessions": 2.0, "median_score_by_lag": {"minus_1": 0.4552599261646507, "minus_2": 0.38073695279730885, "minus_3": 0.2760044033278264, "minus_4": 0.23184559986288322, "minus_5": 0.20116356174503106}}
Sample gate True; operating gate True; sensitivity gate True; quantitative gate False.

### any_transition

#### 1 sessions — FAIL
Quantitative/calibration/operating/robustness gate fails.
Common OOS origins 2,944 (2015-01-06–2026-09-23); 12 blocks; event labels 585, non-events 2,359; distinct event dates 585; base rate 19.87%. Origin states: {'NEUTRAL': 1363, 'RISK-ON': 844, 'DE-RISK': 737}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.4998 | 0.1596 | 0.1757 | 0.4405 | 0.0388 | 0.0549 | PASS |
| state_duration | 0.4834 | 0.1545 | 0.2604 | 0.6224 | 0.0024 | 0.0027 | PASS |
| market | 0.4804 | 0.1537 | 0.2884 | 0.6330 | 0.0040 | 0.0054 | PASS |
- Market vs unconditional: relative LL gain +3.89%, Brier gain +3.72%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0172/+0.0052; middle +0.0218/+0.0066; late +0.0193/+0.0060
- Market vs state_duration: relative LL gain +0.63%, Brier gain +0.50%; 9/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0037/+0.0008; middle +0.0070/+0.0019; late -0.0015/-0.0004
Fixed train-only top-decile operating point: {"alerts": 260, "base_event_rate": 0.19870923913043478, "false_alarms": 176, "false_positive_rate": 0.07460788469690546, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.3230769230769231, "precision_lift": 1.6258777120315582, "recall": 0.14358974358974358, "true_alarms": 84}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 928, "mean_score": 0.19724295888091078, "event_rate": 0.2521551724137931}, {"bin": "0.2\u20130.4", "n": 2016, "mean_score": 0.2054599893584614, "event_rate": 0.17410714285714285}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 1467, "mean_score": 0.14464603366430898, "event_rate": 0.14246762099522836}, {"bin": "0.2\u20130.4", "n": 1477, "mean_score": 0.2572713857682773, "event_rate": 0.25457007447528773}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 1472, "mean_score": 0.1414298283446543, "event_rate": 0.14402173913043478}, {"bin": "0.2\u20130.4", "n": 1472, "mean_score": 0.2587899033301186, "event_rate": 0.25339673913043476}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}]}
Sample gate True; operating gate True; sensitivity gate None; quantitative gate False.

#### 3 sessions — FAIL
Quantitative/calibration/operating/robustness gate fails.
Common OOS origins 2,938 (2015-01-06–2026-09-21); 12 blocks; event labels 966, non-events 1,972; distinct event dates 966; base rate 32.88%. Origin states: {'NEUTRAL': 1360, 'RISK-ON': 841, 'DE-RISK': 737}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.6347 | 0.2213 | 0.2987 | 0.4530 | 0.0080 | 0.0080 | PASS |
| state_duration | 0.6217 | 0.2156 | 0.3921 | 0.5939 | 0.0112 | 0.0931 | PASS |
| market | 0.6169 | 0.2137 | 0.4160 | 0.6047 | 0.0068 | 0.0224 | PASS |
- Market vs unconditional: relative LL gain +2.81%, Brier gain +3.43%; 11/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0197/+0.0085; middle +0.0151/+0.0061; late +0.0188/+0.0081
- Market vs state_duration: relative LL gain +0.77%, Brier gain +0.87%; 10/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0057/+0.0023; middle +0.0092/+0.0037; late -0.0006/-0.0004
Fixed train-only top-decile operating point: {"alerts": 268, "base_event_rate": 0.3287950987066031, "false_alarms": 138, "false_positive_rate": 0.06997971602434078, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.48507462686567165, "precision_lift": 1.47530978647137, "recall": 0.13457556935817805, "true_alarms": 130}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.2\u20130.4", "n": 2938, "mean_score": 0.3367544565147109, "event_rate": 0.3287950987066031}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 64, "mean_score": 0.18812215937824409, "event_rate": 0.28125}, {"bin": "0.2\u20130.4", "n": 2237, "mean_score": 0.31354977759922104, "event_rate": 0.3021904336164506}, {"bin": "0.4\u20130.6", "n": 637, "mean_score": 0.42949594678750563, "event_rate": 0.42700156985871274}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 153, "mean_score": 0.17923225385537922, "event_rate": 0.1568627450980392}, {"bin": "0.2\u20130.4", "n": 2144, "mean_score": 0.31595085124599503, "event_rate": 0.31343283582089554}, {"bin": "0.4\u20130.6", "n": 641, "mean_score": 0.43841416243527503, "event_rate": 0.42121684867394693}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}]}
Sample gate True; operating gate True; sensitivity gate None; quantitative gate False.

#### 5 sessions — FAIL
Quantitative/calibration/operating/robustness gate fails.
Common OOS origins 2,932 (2015-01-06–2026-09-17); 12 blocks; event labels 1,167, non-events 1,765; distinct event dates 1,167; base rate 39.80%. Origin states: {'NEUTRAL': 1355, 'RISK-ON': 840, 'DE-RISK': 737}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.6737 | 0.2403 | 0.3646 | 0.4512 | 0.0334 | 0.0907 | PASS |
| state_duration | 0.6618 | 0.2346 | 0.4671 | 0.5891 | 0.0141 | 0.0237 | PASS |
| market | 0.6574 | 0.2327 | 0.4722 | 0.6028 | 0.0113 | 0.1930 | FAIL |
- Market vs unconditional: relative LL gain +2.41%, Brier gain +3.19%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0159/+0.0076; middle +0.0206/+0.0097; late +0.0123/+0.0057
- Market vs state_duration: relative LL gain +0.66%, Brier gain +0.81%; 10/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0041/+0.0019; middle +0.0112/+0.0051; late -0.0022/-0.0013
Fixed train-only top-decile operating point: {"alerts": 280, "base_event_rate": 0.3980218281036835, "false_alarms": 136, "false_positive_rate": 0.07705382436260623, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.5142857142857142, "precision_lift": 1.292104296731546, "recall": 0.12339331619537275, "true_alarms": 144}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.2\u20130.4", "n": 412, "mean_score": 0.3947582694556865, "event_rate": 0.4854368932038835}, {"bin": "0.4\u20130.6", "n": 2520, "mean_score": 0.4077234924969898, "event_rate": 0.38373015873015875}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.2\u20130.4", "n": 1332, "mean_score": 0.3382624772786616, "event_rate": 0.31456456456456455}, {"bin": "0.4\u20130.6", "n": 1600, "mean_score": 0.46137777999940255, "event_rate": 0.4675}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 8, "mean_score": 0.1929984299070099, "event_rate": 0.0}, {"bin": "0.2\u20130.4", "n": 1323, "mean_score": 0.3355606709188616, "event_rate": 0.31594860166288735}, {"bin": "0.4\u20130.6", "n": 1601, "mean_score": 0.46440063995775904, "event_rate": 0.4678326046221112}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}]}
Sample gate True; operating gate True; sensitivity gate None; quantitative gate False.

### de_risk_exit

#### 1 sessions — INSUFFICIENT EVIDENCE
Insufficient distinct events/origins to decide.
Common OOS origins 737 (2015-01-06–2026-09-16); 12 blocks; event labels 132, non-events 605; distinct event dates 132; base rate 17.91%. Origin states: {'DE-RISK': 737}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.4729 | 0.1479 | 0.1404 | 0.3705 | 0.0032 | 0.0032 | PASS |
| state_duration | 0.4328 | 0.1359 | 0.3292 | 0.7090 | 0.0254 | 0.0373 | PASS |
| market | 0.3380 | 0.1113 | 0.4965 | 0.8600 | 0.0333 | 0.0933 | FAIL |
- Market vs unconditional: relative LL gain +28.53%, Brier gain +24.74%; 11/12 dual-metric fold wins. Era deltas LL/Brier: early +0.1341/+0.0356; middle +0.1280/+0.0302; late +0.1427/+0.0440
- Market vs state_duration: relative LL gain +21.89%, Brier gain +18.10%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0908/+0.0224; middle +0.1001/+0.0227; late +0.0933/+0.0287
Fixed train-only top-decile operating point: {"alerts": 78, "base_event_rate": 0.1791044776119403, "false_alarms": 38, "false_positive_rate": 0.0628099173553719, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.5128205128205128, "precision_lift": 2.8632478632478633, "recall": 0.30303030303030304, "true_alarms": 40}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 737, "mean_score": 0.1822734643126929, "event_rate": 0.1791044776119403}, {"bin": "0.2\u20130.4", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 456, "mean_score": 0.1211099871310091, "event_rate": 0.10307017543859649}, {"bin": "0.2\u20130.4", "n": 281, "mean_score": 0.26521217494047394, "event_rate": 0.302491103202847}, {"bin": "0.4\u20130.6", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 488, "mean_score": 0.06616312814722738, "event_rate": 0.055327868852459015}, {"bin": "0.2\u20130.4", "n": 140, "mean_score": 0.2924412926087377, "event_rate": 0.38571428571428573}, {"bin": "0.4\u20130.6", "n": 92, "mean_score": 0.5018072445986561, "event_rate": 0.43478260869565216}, {"bin": "0.6\u20130.8", "n": 17, "mean_score": 0.6462282499573822, "event_rate": 0.6470588235294118}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}]}
Sample gate False; operating gate True; sensitivity gate None; quantitative gate False.

#### 3 sessions — INSUFFICIENT EVIDENCE
Insufficient distinct events/origins to decide.
Common OOS origins 737 (2015-01-06–2026-09-16); 12 blocks; event labels 278, non-events 459; distinct event dates 132; base rate 37.72%. Origin states: {'DE-RISK': 737}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.6709 | 0.2389 | 0.3068 | 0.3543 | 0.1331 | 0.1474 | FAIL |
| state_duration | 0.6001 | 0.2051 | 0.5687 | 0.7098 | 0.0796 | 0.1324 | FAIL |
| market | 0.4746 | 0.1563 | 0.7141 | 0.8421 | 0.0312 | 0.0522 | PASS |
- Market vs unconditional: relative LL gain +29.26%, Brier gain +34.56%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.1801/+0.0757; middle +0.2184/+0.0906; late +0.1905/+0.0813
- Market vs state_duration: relative LL gain +20.91%, Brier gain +23.80%; 11/12 dual-metric fold wins. Era deltas LL/Brier: early +0.1042/+0.0391; middle +0.1594/+0.0628; late +0.1128/+0.0446
Fixed train-only top-decile operating point: {"alerts": 74, "base_event_rate": 0.37720488466757124, "false_alarms": 17, "false_positive_rate": 0.037037037037037035, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.7702702702702703, "precision_lift": 2.04204744312658, "recall": 0.20503597122302158, "true_alarms": 57}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.2\u20130.4", "n": 360, "mean_score": 0.3819631098529921, "event_rate": 0.5}, {"bin": "0.4\u20130.6", "n": 377, "mean_score": 0.4073398206491016, "event_rate": 0.259946949602122}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 86, "mean_score": 0.1698991851125222, "event_rate": 0.3023255813953488}, {"bin": "0.2\u20130.4", "n": 308, "mean_score": 0.2907554010694809, "event_rate": 0.18831168831168832}, {"bin": "0.4\u20130.6", "n": 306, "mean_score": 0.5090733198827563, "event_rate": 0.5588235294117647}, {"bin": "0.6\u20130.8", "n": 37, "mean_score": 0.6071613939920615, "event_rate": 0.6216216216216216}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 253, "mean_score": 0.09571099247617419, "event_rate": 0.043478260869565216}, {"bin": "0.2\u20130.4", "n": 134, "mean_score": 0.2945944558389038, "event_rate": 0.3208955223880597}, {"bin": "0.4\u20130.6", "n": 148, "mean_score": 0.493962013984339, "event_rate": 0.5067567567567568}, {"bin": "0.6\u20130.8", "n": 132, "mean_score": 0.7069065818126287, "event_rate": 0.7121212121212122}, {"bin": "0.8\u20131.0", "n": 70, "mean_score": 0.8379232571571845, "event_rate": 0.7857142857142857}]}
Sample gate False; operating gate True; sensitivity gate None; quantitative gate False.

#### 5 sessions — INSUFFICIENT EVIDENCE
Insufficient distinct events/origins to decide.
Common OOS origins 737 (2015-01-06–2026-09-16); 12 blocks; event labels 363, non-events 374; distinct event dates 132; base rate 49.25%. Origin states: {'DE-RISK': 737}.
Distinct event dates are not independent OOS origins; h-session labels overlap. No independence-based uncertainty interval is claimed.
| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| unconditional | 0.7047 | 0.2558 | 0.4259 | 0.3486 | 0.0254 | 0.0254 | PASS |
| state_duration | 0.6288 | 0.2179 | 0.6740 | 0.7062 | 0.0609 | 0.8039 | FAIL |
| market | 0.5203 | 0.1727 | 0.8042 | 0.8214 | 0.0349 | 0.0727 | PASS |
- Market vs unconditional: relative LL gain +26.17%, Brier gain +32.49%; 12/12 dual-metric fold wins. Era deltas LL/Brier: early +0.1549/+0.0750; middle +0.2627/+0.1157; late +0.1354/+0.0585
- Market vs state_duration: relative LL gain +17.25%, Brier gain +20.77%; 9/12 dual-metric fold wins. Era deltas LL/Brier: early +0.0869/+0.0411; middle +0.1895/+0.0788; late +0.0488/+0.0158
Fixed train-only top-decile operating point: {"alerts": 75, "base_event_rate": 0.4925373134328358, "false_alarms": 6, "false_positive_rate": 0.016042780748663103, "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS", "precision": 0.92, "precision_lift": 1.8678787878787881, "recall": 0.19008264462809918, "true_alarms": 69}
Classwise fixed-bin reliability: {"unconditional": [{"bin": "0.0\u20130.2", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.2\u20130.4", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.4\u20130.6", "n": 737, "mean_score": 0.5178958953797651, "event_rate": 0.4925373134328358}, {"bin": "0.6\u20130.8", "n": 0, "mean_score": null, "event_rate": null}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "state_duration": [{"bin": "0.0\u20130.2", "n": 4, "mean_score": 0.19612549285256253, "event_rate": 1.0}, {"bin": "0.2\u20130.4", "n": 235, "mean_score": 0.3184112179059632, "event_rate": 0.2936170212765957}, {"bin": "0.4\u20130.6", "n": 246, "mean_score": 0.5076452426080269, "event_rate": 0.42276422764227645}, {"bin": "0.6\u20130.8", "n": 252, "mean_score": 0.6787954730085296, "event_rate": 0.7380952380952381}, {"bin": "0.8\u20131.0", "n": 0, "mean_score": null, "event_rate": null}], "market": [{"bin": "0.0\u20130.2", "n": 125, "mean_score": 0.13569189833002307, "event_rate": 0.104}, {"bin": "0.2\u20130.4", "n": 151, "mean_score": 0.29119745689169496, "event_rate": 0.2185430463576159}, {"bin": "0.4\u20130.6", "n": 137, "mean_score": 0.5064148181111826, "event_rate": 0.5328467153284672}, {"bin": "0.6\u20130.8", "n": 176, "mean_score": 0.702986833232793, "event_rate": 0.6704545454545454}, {"bin": "0.8\u20131.0", "n": 148, "mean_score": 0.8610991597404639, "event_rate": 0.8513513513513513}]}
Sample gate False; operating gate True; sensitivity gate None; quantitative gate False.

## Fixed-cutoff sensitivity appendix (DE-RISK entry ONLY)
Neither alternative changes the frozen classifier or selects a model. Changed event counts/gain direction signal label fragility.
```json
{
  "30/70": {
    "1": {
      "distinct_entry_dates": 98,
      "events": 98,
      "market_vs_duration": {
        "dual_metric_fold_wins": 12,
        "folds": 12,
        "relative_brier_gain": 0.08154796843653457,
        "relative_log_loss_gain": 0.17644664814543085
      },
      "oos_origins": 2362,
      "same_positive_direction": true
    },
    "3": {
      "distinct_entry_dates": 98,
      "events": 244,
      "market_vs_duration": {
        "dual_metric_fold_wins": 12,
        "folds": 12,
        "relative_brier_gain": 0.10606357271640997,
        "relative_log_loss_gain": 0.1384879520533326
      },
      "oos_origins": 2356,
      "same_positive_direction": true
    },
    "5": {
      "distinct_entry_dates": 98,
      "events": 365,
      "market_vs_duration": {
        "dual_metric_fold_wins": 11,
        "folds": 12,
        "relative_brier_gain": 0.10710330956400449,
        "relative_log_loss_gain": 0.10742770079676667
      },
      "oos_origins": 2350,
      "same_positive_direction": true
    }
  },
  "40/60": {
    "1": {
      "distinct_entry_dates": 139,
      "events": 139,
      "market_vs_duration": {
        "dual_metric_fold_wins": 11,
        "folds": 12,
        "relative_brier_gain": 0.0667037544452372,
        "relative_log_loss_gain": 0.08386522257617975
      },
      "oos_origins": 2001,
      "same_positive_direction": true
    },
    "3": {
      "distinct_entry_dates": 139,
      "events": 326,
      "market_vs_duration": {
        "dual_metric_fold_wins": 10,
        "folds": 12,
        "relative_brier_gain": 0.0634511425168456,
        "relative_log_loss_gain": 0.05534077543578564
      },
      "oos_origins": 1995,
      "same_positive_direction": true
    },
    "5": {
      "distinct_entry_dates": 139,
      "events": 467,
      "market_vs_duration": {
        "dual_metric_fold_wins": 11,
        "folds": 12,
        "relative_brier_gain": 0.059648758322484376,
        "relative_log_loss_gain": 0.04643501610920972
      },
      "oos_origins": 1989,
      "same_positive_direction": true
    }
  }
}
```

## Decision
No production promotion and no Signal Hub connection. The snapshot was retrieved after historical forecast origins; date-ordered retrospective evidence cannot certify live forecast availability.
