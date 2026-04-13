# GLiNER context injection — Pass 1

- Model: `fastino/gliner2-base-v1`
- Corpus: Ai4Privacy, 315 rows (105 templates × 3 seeds)
- Seeds: [42, 7, 101]
- Thresholds: [0.5, 0.7, 0.8]
- Bootstrap resamples: 1000 (BCa 95%)

## Threshold 0.5

| Strategy | Macro F1 | 95% CI | vs baseline Δ | Δ 95% CI | Excl 0 | Excl +0.02 | McNemar p | (b, c) |
|---|---:|---|---:|---|:-:|:-:|---:|---:|
| `baseline` | **0.4492** | [0.424, 0.476] (w=0.051) | — | — | — | — | — | — |
| `s1_nl_prompt` | 0.5667 | [0.538, 0.593] (w=0.056) | +0.1176 | [+0.092, +0.141] (w=0.048) | ✓ | ✓ | 0.4807 | (7, 11) |
| `s2_per_column_descriptions` | 0.4440 | [0.418, 0.470] (w=0.052) | -0.0051 | [-0.028, +0.014] (w=0.042) | × | × | 0.0000 | (27, 2) |
| `s3_label_narrowing` | 0.4561 | [0.431, 0.488] (w=0.057) | +0.0070 | [-0.008, +0.026] (w=0.034) | × | × | 0.0075 | (15, 3) |

## Threshold 0.7

| Strategy | Macro F1 | 95% CI | vs baseline Δ | Δ 95% CI | Excl 0 | Excl +0.02 | McNemar p | (b, c) |
|---|---:|---|---:|---|:-:|:-:|---:|---:|
| `baseline` | **0.5260** | [0.496, 0.556] (w=0.060) | — | — | — | — | — | — |
| `s1_nl_prompt` | 0.6146 | [0.581, 0.647] (w=0.066) | +0.0887 | [+0.058, +0.123] (w=0.065) | ✓ | ✓ | 1.0000 | (10, 10) |
| `s2_per_column_descriptions` | 0.4657 | [0.440, 0.493] (w=0.053) | -0.0603 | [-0.084, -0.040] (w=0.044) | ✓ | × | 0.0000 | (39, 0) |
| `s3_label_narrowing` | 0.5264 | [0.496, 0.560] (w=0.064) | +0.0004 | [-0.022, +0.028] (w=0.050) | × | × | 0.1671 | (13, 6) |

## Threshold 0.8

| Strategy | Macro F1 | 95% CI | vs baseline Δ | Δ 95% CI | Excl 0 | Excl +0.02 | McNemar p | (b, c) |
|---|---:|---|---:|---|:-:|:-:|---:|---:|
| `baseline` | **0.5278** | [0.497, 0.563] (w=0.066) | — | — | — | — | — | — |
| `s1_nl_prompt` | 0.6164 | [0.585, 0.650] (w=0.066) | +0.0887 | [+0.050, +0.131] (w=0.082) | ✓ | ✓ | 0.5847 | (13, 17) |
| `s2_per_column_descriptions` | 0.5178 | [0.494, 0.546] (w=0.052) | -0.0100 | [-0.036, +0.014] (w=0.050) | × | × | 0.0002 | (13, 0) |
| `s3_label_narrowing` | 0.5215 | [0.488, 0.560] (w=0.072) | -0.0063 | [-0.026, +0.019] (w=0.045) | × | × | 0.3018 | (10, 5) |

## Context-kind stratification (threshold=0.8)

| Strategy | empty | helpful | misleading |
|---|---:|---:|---:|
| `baseline` | 0.5173 | 0.5251 | 0.5461 |
| `s1_nl_prompt` | 0.5564 | 0.6706 | 0.6031 |
| `s2_per_column_descriptions` | 0.5196 | 0.5779 | 0.5303 |
| `s3_label_narrowing` | 0.5316 | 0.6008 | 0.5068 |

