# Kill test v2 — frozen test days scored once (protocol v2, D-0006; setting D-0007)

**Verdict: PASS** — P1 14/20 sites (need ≥ 10) · P2 15/16 event sites (need ≥ 70 %) · P3 registration 0.957 (need ≥ 0.90).

Test days: 2026-10-04 00Z – 2026-10-14 00Z, daylight registered frames, 20 sites of `data/sites/kill_test.yaml`. Calibration: all frames before 2026-10-03 00Z (history + SLICE_01 fit window). Setting (D-0007, hash in `results/constants.sha256`): block 4 px, ROI reliability ≥ 0.8, ridge λ 1.0, smoothing kalman. Produced by `scripts/scene_score.py`; per-site numbers in `results/kill_test_v2.csv`.

P3 is computed over the 30-day window's daylight frames, as in SLICE_01 (95.7 %); the test-day rate per site is in the table.

## Per-site results (ft)

| site | tier | n | reg (test) | MAE | nMAE | P1 | ev frames | MAE ev / LKV-24h ev | P2 | 15 min pers. | 24 h pers. | const | ρ | flood bacc (cam / 24h) | σ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TX_Cowhouse_Ck_at_Old_Georgetown_Rd_nr_Ft_Hood | C | 236 | 0.99 | 0.21 | 0.15 | ✔ | 25 | 0.64 / 1.01 | ✔ | 0.00 | 0.16 | 0.47 | 0.65 | 0.80 / 0.94 | 0.57 |
| TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris | C | 119 | 1.00 | 0.62 | 0.33 | ✘ | 8 | 0.20 / 0.84 | ✔ | 0.00 | 0.11 | 0.19 | -0.10 | 0.58 / 0.97 | 0.65 |
| TX_Buffalo_Bayou_at_State_HWY_6_near_Addicks | B | 113 | 0.97 | 0.27 | 0.09 | ✔ | 39 | 0.23 / 1.06 | ✔ | 0.02 | 0.44 | 1.61 | 0.56 | 0.74 / 0.82 | 0.41 |
| TX_Clear_Fk_Trinity_Rv_at_Ft_Worth | B | 120 | 1.00 | 0.13 | 0.11 | ✔ | 24 | 0.20 / 0.91 | ✔ | 0.01 | 0.24 | 0.27 | 0.90 | 0.99 / 0.44 | 0.29 |
| TX_White_Rk_Ck_at_Greenville_Ave_Dallas | C | 58 | 0.48 | 0.78 | 0.72 | ✘ | 5 | 0.56 / 0.52 | ✘ | 0.01 | 0.08 | 0.24 | 0.19 | — / — | 0.54 |
| TX_Langham_Creek_at_Addicks_Reservoir_Outflow_near_Addicks | B | 211 | 0.97 | 0.49 | 0.10 | ✘ | 101 | 0.57 / 2.02 | ✔ | 0.02 | 1.01 | 3.74 | 0.85 | 0.95 / 0.75 | 0.53 |
| WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet | A | 113 | 0.94 | 0.09 | 0.02 | ✔ | 12 | 0.07 / 0.34 | ✔ | 0.00 | 0.10 | 0.14 | 0.79 | — / — | 0.67 |
| WI_Swan_Creek_at_Lalor_Road_near_Fitchburg | C | 113 | 0.94 | 0.06 | 0.04 | ✔ | 0 | — / — | — | 0.00 | 0.02 | 0.02 | 0.68 | — / — | 0.43 |
| MN_Root_River_near_Pilot_Mound | C | 94 | 0.85 | 0.45 | 0.10 | ✘ | 0 | — / — | — | 0.01 | 0.05 | 0.12 | 0.52 | — / — | 1.74 |
| NY_East_Branch_Delaware_River_at_Hancock_Staff | A | 114 | 1.00 | 0.06 | 0.04 | ✔ | 20 | 0.07 / 0.59 | ✔ | 0.00 | 0.13 | 0.46 | 0.63 | — / — | 0.87 |
| NY_Neversink_River_at_Godeffroy | B | 114 | 0.96 | 0.06 | 0.04 | ✔ | 23 | 0.11 / 0.51 | ✔ | 0.00 | 0.12 | 0.24 | 0.76 | — / — | 0.38 |
| NJ_Stony_Brook_at_Princeton | B | 111 | 0.93 | 0.11 | 0.06 | ✔ | 26 | 0.13 / 1.09 | ✔ | 0.01 | 0.29 | 0.31 | 0.68 | 0.96 / 0.51 | 0.40 |
| NJ_Big_Brook_near_Marlboro | C | 58 | 0.48 | 0.15 | 0.17 | ✔ | 11 | 0.11 / 0.40 | ✔ | 0.01 | 0.11 | 0.15 | -0.01 | 0.61 / 0.65 | 0.38 |
| OH_East_Fork_Little_Miami_River_at_Perintown | B | 120 | 1.00 | 0.48 | 0.11 | ✘ | 0 | — / — | — | 0.00 | 0.03 | 0.65 | 0.60 | — / — | 0.74 |
| OH_Bean_Creek_at_Powers | B | 113 | 0.94 | 0.27 | 0.05 | ✔ | 30 | 0.22 / 0.58 | ✔ | 0.00 | 0.22 | 0.34 | 0.76 | — / — | 1.10 |
| CO_Animas_River_at_Durango | B | 230 | 0.99 | 0.15 | 0.07 | ✔ | 20 | 0.02 / 0.29 | ✔ | 0.00 | 0.10 | 0.59 | 0.87 | — / — | 0.63 |
| CO_Sand_Creek_at_Mouth_nr_Commerce_City | C | 237 | 1.00 | 0.07 | 0.09 | ✔ | 0 | — / — | — | 0.00 | 0.01 | 0.10 | 0.15 | — / — | 0.16 |
| IL_Salt_Creek_at_Wood_Dale | B | 119 | 1.00 | 0.09 | 0.02 | ✔ | 43 | 0.14 / 0.90 | ✔ | 0.01 | 0.39 | 0.48 | 0.91 | — / — | 0.32 |
| PA_Brandywine_Creek_at_Chadds_Ford | C | 233 | 1.00 | 0.31 | 0.19 | ✘ | 51 | 0.37 / 1.92 | ✔ | 0.01 | 0.45 | 0.36 | 0.63 | 0.94 / 0.52 | 1.01 |
| CA_First_Mallard_Branch_nr_Fairfield | B | 208 | 0.95 | 0.39 | 0.09 | ✔ | 143 | 0.35 / 0.58 | ✔ | 0.15 | 0.43 | 1.29 | 0.93 | 0.93 / 0.88 | 0.49 |

## Outage gap-fill: camera vs last-known value (MAE ft, all scored frames)

| site | 6 h LKV / cam | 24 h LKV / cam | 72 h LKV / cam | 7 d LKV / cam |
|---|---|---|---|---|
| TX_Cowhouse_Ck_at_Old_Georgetown_Rd_nr_Ft_Hood | 0.02 / 0.21 | 0.16 / 0.21 | 0.57 / 0.21 | 0.92 / 0.21 |
| TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris | 0.05 / 0.62 | 0.11 / 0.62 | 0.70 / 0.62 | 0.98 / 0.62 |
| TX_Buffalo_Bayou_at_State_HWY_6_near_Addicks | 0.18 / 0.27 | 0.44 / 0.27 | 0.88 / 0.27 | 1.79 / 0.27 |
| TX_Clear_Fk_Trinity_Rv_at_Ft_Worth | 0.13 / 0.13 | 0.24 / 0.13 | 0.38 / 0.13 | 0.82 / 0.13 |
| TX_White_Rk_Ck_at_Greenville_Ave_Dallas | 0.03 / 0.78 | 0.08 / 0.78 | 0.32 / 0.78 | 1.57 / 0.78 |
| TX_Langham_Creek_at_Addicks_Reservoir_Outflow_near_Addicks | 0.46 / 0.49 | 1.01 / 0.49 | 2.49 / 0.49 | 4.23 / 0.49 |
| WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet | 0.02 / 0.09 | 0.10 / 0.09 | 0.47 / 0.09 | 0.66 / 0.09 |
| WI_Swan_Creek_at_Lalor_Road_near_Fitchburg | 0.01 / 0.06 | 0.02 / 0.06 | 0.18 / 0.06 | 0.23 / 0.06 |
| MN_Root_River_near_Pilot_Mound | 0.01 / 0.45 | 0.05 / 0.45 | 0.16 / 0.45 | 0.44 / 0.45 |
| NY_East_Branch_Delaware_River_at_Hancock_Staff | 0.03 / 0.06 | 0.13 / 0.06 | 0.20 / 0.06 | 0.31 / 0.06 |
| NY_Neversink_River_at_Godeffroy | 0.03 / 0.06 | 0.12 / 0.06 | 0.18 / 0.06 | 0.31 / 0.06 |
| NJ_Stony_Brook_at_Princeton | 0.14 / 0.11 | 0.29 / 0.11 | 0.35 / 0.11 | 0.79 / 0.11 |
| NJ_Big_Brook_near_Marlboro | 0.04 / 0.15 | 0.11 / 0.15 | 0.08 / 0.15 | 0.38 / 0.15 |
| OH_East_Fork_Little_Miami_River_at_Perintown | 0.01 / 0.48 | 0.03 / 0.48 | 0.09 / 0.48 | 0.45 / 0.48 |
| OH_Bean_Creek_at_Powers | 0.05 / 0.27 | 0.22 / 0.27 | 0.73 / 0.27 | 1.08 / 0.27 |
| CO_Animas_River_at_Durango | 0.03 / 0.15 | 0.10 / 0.15 | 0.31 / 0.15 | 0.60 / 0.15 |
| CO_Sand_Creek_at_Mouth_nr_Commerce_City | 0.01 / 0.07 | 0.01 / 0.07 | 0.03 / 0.07 | 0.14 / 0.07 |
| IL_Salt_Creek_at_Wood_Dale | 0.12 / 0.09 | 0.39 / 0.09 | 1.03 / 0.09 | 1.64 / 0.09 |
| PA_Brandywine_Creek_at_Chadds_Ford | 0.21 / 0.31 | 0.45 / 0.31 | 0.40 / 0.31 | 0.64 / 0.31 |
| CA_First_Mallard_Branch_nr_Fairfield | 2.16 / 0.39 | 0.43 / 0.39 | 1.19 / 0.39 | 1.69 / 0.39 |

## Plots

Per site: `results/kill_test_v2/<cam>_ts.png` (camera ± σ vs gauge, event frames shaded) and `results/kill_test_v2/<cam>_floodheight.png` (h* per block; grey = not reliable).

### TX_Cowhouse_Ck_at_Old_Georgetown_Rd_nr_Ft_Hood

![ts](kill_test_v2/TX_Cowhouse_Ck_at_Old_Georgetown_Rd_nr_Ft_Hood_ts.png)

![h*](kill_test_v2/TX_Cowhouse_Ck_at_Old_Georgetown_Rd_nr_Ft_Hood_floodheight.png)

### TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris

![ts](kill_test_v2/TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris_ts.png)

![h*](kill_test_v2/TX_Tenmile_Ck_at_Parkinson_Rd_nr_Ferris_floodheight.png)

### TX_Buffalo_Bayou_at_State_HWY_6_near_Addicks

![ts](kill_test_v2/TX_Buffalo_Bayou_at_State_HWY_6_near_Addicks_ts.png)

![h*](kill_test_v2/TX_Buffalo_Bayou_at_State_HWY_6_near_Addicks_floodheight.png)

### TX_Clear_Fk_Trinity_Rv_at_Ft_Worth

![ts](kill_test_v2/TX_Clear_Fk_Trinity_Rv_at_Ft_Worth_ts.png)

![h*](kill_test_v2/TX_Clear_Fk_Trinity_Rv_at_Ft_Worth_floodheight.png)

### TX_White_Rk_Ck_at_Greenville_Ave_Dallas

![ts](kill_test_v2/TX_White_Rk_Ck_at_Greenville_Ave_Dallas_ts.png)

![h*](kill_test_v2/TX_White_Rk_Ck_at_Greenville_Ave_Dallas_floodheight.png)

### TX_Langham_Creek_at_Addicks_Reservoir_Outflow_near_Addicks

![ts](kill_test_v2/TX_Langham_Creek_at_Addicks_Reservoir_Outflow_near_Addicks_ts.png)

![h*](kill_test_v2/TX_Langham_Creek_at_Addicks_Reservoir_Outflow_near_Addicks_floodheight.png)

### WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet

![ts](kill_test_v2/WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet_ts.png)

![h*](kill_test_v2/WI_East_Branch_Pecatonica_River_near_Blanchardville_Bullet_floodheight.png)

### WI_Swan_Creek_at_Lalor_Road_near_Fitchburg

![ts](kill_test_v2/WI_Swan_Creek_at_Lalor_Road_near_Fitchburg_ts.png)

![h*](kill_test_v2/WI_Swan_Creek_at_Lalor_Road_near_Fitchburg_floodheight.png)

### MN_Root_River_near_Pilot_Mound

![ts](kill_test_v2/MN_Root_River_near_Pilot_Mound_ts.png)

![h*](kill_test_v2/MN_Root_River_near_Pilot_Mound_floodheight.png)

### NY_East_Branch_Delaware_River_at_Hancock_Staff

![ts](kill_test_v2/NY_East_Branch_Delaware_River_at_Hancock_Staff_ts.png)

![h*](kill_test_v2/NY_East_Branch_Delaware_River_at_Hancock_Staff_floodheight.png)

### NY_Neversink_River_at_Godeffroy

![ts](kill_test_v2/NY_Neversink_River_at_Godeffroy_ts.png)

![h*](kill_test_v2/NY_Neversink_River_at_Godeffroy_floodheight.png)

### NJ_Stony_Brook_at_Princeton

![ts](kill_test_v2/NJ_Stony_Brook_at_Princeton_ts.png)

![h*](kill_test_v2/NJ_Stony_Brook_at_Princeton_floodheight.png)

### NJ_Big_Brook_near_Marlboro

![ts](kill_test_v2/NJ_Big_Brook_near_Marlboro_ts.png)

![h*](kill_test_v2/NJ_Big_Brook_near_Marlboro_floodheight.png)

### OH_East_Fork_Little_Miami_River_at_Perintown

![ts](kill_test_v2/OH_East_Fork_Little_Miami_River_at_Perintown_ts.png)

![h*](kill_test_v2/OH_East_Fork_Little_Miami_River_at_Perintown_floodheight.png)

### OH_Bean_Creek_at_Powers

![ts](kill_test_v2/OH_Bean_Creek_at_Powers_ts.png)

![h*](kill_test_v2/OH_Bean_Creek_at_Powers_floodheight.png)

### CO_Animas_River_at_Durango

![ts](kill_test_v2/CO_Animas_River_at_Durango_ts.png)

![h*](kill_test_v2/CO_Animas_River_at_Durango_floodheight.png)

### CO_Sand_Creek_at_Mouth_nr_Commerce_City

![ts](kill_test_v2/CO_Sand_Creek_at_Mouth_nr_Commerce_City_ts.png)

![h*](kill_test_v2/CO_Sand_Creek_at_Mouth_nr_Commerce_City_floodheight.png)

### IL_Salt_Creek_at_Wood_Dale

![ts](kill_test_v2/IL_Salt_Creek_at_Wood_Dale_ts.png)

![h*](kill_test_v2/IL_Salt_Creek_at_Wood_Dale_floodheight.png)

### PA_Brandywine_Creek_at_Chadds_Ford

![ts](kill_test_v2/PA_Brandywine_Creek_at_Chadds_Ford_ts.png)

![h*](kill_test_v2/PA_Brandywine_Creek_at_Chadds_Ford_floodheight.png)

### CA_First_Mallard_Branch_nr_Fairfield

![ts](kill_test_v2/CA_First_Mallard_Branch_nr_Fairfield_ts.png)

![h*](kill_test_v2/CA_First_Mallard_Branch_nr_Fairfield_floodheight.png)
