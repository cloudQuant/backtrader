# Standard metric contract

| Key | Unit | Nullable |
| --- | --- | --- |
| `bar_num` | bars seen by the strategy | no |
| `buy_count` | long trade records | no |
| `sell_count` | short trade records | no |
| `win_count` | closed winning trades | no |
| `loss_count` | closed losing trades | no |
| `trade_num` | trade records | no |
| `final_value` | account currency | no |
| `sharpe_ratio` | dimensionless | yes |
| `annual_return` | ratio | no |
| `max_drawdown` | percent | no |
| `return_rate` | percent | no |

Integer metrics compare exactly. Floats use `rel_tol=1e-7` and `abs_tol=1e-9`; `final_value` uses
`rel_tol=1e-9` and `abs_tol=1e-6`. Null equals only null. Missing fields, NaN, and Infinity fail.
