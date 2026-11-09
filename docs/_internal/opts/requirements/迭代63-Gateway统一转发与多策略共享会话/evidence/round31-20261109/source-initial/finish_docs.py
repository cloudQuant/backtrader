from pathlib import Path
import json
BT=Path('/Users/yunjinqi/Documents/new_projects/backtrader');root=BT/'docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话'
report_name='实施第三十一轮BT稀疏事件消费与通知恢复审阅-2026-11-09.md'
commits=json.loads(Path('/tmp/iter63-r31-primary/product-commits.json').read_text());b=commits['heads'][str(BT)];s=commits['heads'][str(BT.parent/'bt_api_py')]
p=root/'archived'/report_name;t=p.read_text(encoding='utf-8-sig').replace('状态：本轮验收收口中；','状态：本轮限定源码/隔离安装检查完成，完整生产接线继续；')
old='待最终原始日志和提交核对完成后，在此补入精确结果。初始源码为BT984 passed/1 strict xfailed/1 warning，SDK382 passed/2 warnings；'
new='最终同65个BT文件源码v2/安装v4均为 **984 passed、1 strict xfailed、1 warning**；同20个SDK文件源码/安装均为 **382 passed**，源码2 warnings、安装1 warning。'
assert old in t;t=t.replace(old,new)
t=t.replace('最终BT源码/安装须同集复跑。','最终BT源码/安装已用同集复跑，产品wheel未重建。')
t=t.replace('全部源码副本、测试/helper、wheel成员与Git核对完成后补充清单位置。',f'''主代理独立核对1001项源码、137项测试/helper，去重{commits['unique_git_paths_verified']}个Git路径，与最终提交逐字节一致；SDK310、BT682个完整包成员、README metadata及六个固定依赖wheel字节一致。SDK21/BT74冻结输入也与最终工作树/副本相符。

最终源码记录SDK14个进程、BT47个进程；安装记录SDK14个进程、BT48个进程。各BT组均有13个进程缺退出审计，SDK已记录进程退出审计完整；不能外推全部进程或完整沙箱。主代理Git核验初稿误假设全部helper只归SDK/BT，提交后遇到两项CTP公开测试helper而断言失败；修正为按三个真实repo的HEAD批量核对后通过。初稿原stderr仅在工具输出，未保存单独原始日志，不声称已有该日志文件。''')
t += f'''

## 6. 提交与归档

SDK本地dev提交 **`{s}`**；BT产品/测试本地dev提交 **`{b}`**，均未推送。源码/安装摘要分别见[源码最终BT](../evidence/round31-20261109/source-final-bt/bt-source.log)、[源码SDK](../evidence/round31-20261109/source-initial/sdk-source.log)、[安装最终BT](../evidence/round31-20261109/install/bt-frozen-v4.log)、[安装SDK](../evidence/round31-20261109/install/sdk-frozen-final.log)。

[证据总清单](../evidence/round31-20261109/manifest.json)、[Git最终核对](../evidence/round31-20261109/source-initial/product-commits.json)、[主代理包成员核对](../evidence/round31-20261109/source-initial/primary-payload-verification.json)、[安装最终复核](../evidence/round31-20261109/install/verify-final.log)记录精确边界。早期失败、修复前后独立复现、最终owned输入和原fixture版本一并归档。现有无关CLAUDE与相邻迭代修改、原迭代63计划12增10删保留，未纳入本轮提交。
'''
p.write_text(t,encoding='utf-8-sig')
p=root/'实施基线与分轮记录-2026-11-08.md';t=p.read_text(encoding='utf-8-sig');assert '## 第三十一轮' not in t
t+=f'''

## 第三十一轮：BT稀疏事件消费与通知恢复（2026-11-09）

实现SDK显式时间解释、BT真实稀疏执行流消费与原Strategy时点恢复、日期无通知检查点及原pending v5首事件前订单描述端口。独立审阅修复E075/E076/E078/E079及T018；E077本地提交通知、E080旧资金/持仓读取隔离和E074完整首次提交恢复仍OPEN。已绑定消费者的submit/cancel尚未装配，不能按config启动完整策略交易。

最终同65个BT文件源码/安装各984 passed、1 strict xfailed、1 warning；同20个SDK文件各382 passed（源码2 warnings、安装1 warning）。SDK `{s}`、BT产品 `{b}` 已本地dev提交，未推送。主代理核对1001源码/137测试helper、去重{commits['unique_git_paths_verified']}个路径与Git及SDK310/BT682完整包成员。源码BT47、安装BT48已记录进程各13缺退出审计，SDK两组各14进程退出审计完整。

[第三十一轮审阅](archived/{report_name})保留原镜像/helper错误、被停止的合成测试、四测试fixture导出修正及Git核验脚本CTP helper归属修正。六个固定依赖wheel保持，ZMQ/Monitor仍是记录的editable；真实账户、完整resolver和跨平台未验。正式14步仍13 GAP/1 NOT_RUN，整期继续。
''';p.write_text(t,encoding='utf-8-sig')
p=root/'开发验收状态矩阵.md';t=p.read_text(encoding='utf-8-sig');pos=t.index('\n')+1
t=t[:pos]+f'''\nR31限定源码/安装已完成：BT同65文件各984 passed/1 strict xfailed，SDK同20文件各382 passed。显式流消费、原通知时点重投、无通知日期检查点和pending v5订单描述已有证据；完整下单/config/资金读取未接通。[R31审阅](archived/{report_name})。\n'''+t[pos:]
t=t.replace('更新：2026-11-09，已归档至 R30；真实框架对象、显式通知提交/恢复及 SDK providerless 能力入口已有局部源码与隔离安装验证。完整生产消费与远端ACK链路尚未接通，整期 **IN_PROGRESS / 未验收**。','更新：2026-11-09，已归档至 R31；已有订单的显式事件消费、持久通知及远端ACK在独立Gateway合成进程通过。完整生产配置/提交与首事件前恢复、策略资金及查询隔离仍未接通，整期 **IN_PROGRESS / 未验收**。')
line=next(x for x in t.splitlines() if x.startswith('| 63.06 '))
new_line='| 63.06 BT Gateway 模式 | GAP | pending逻辑意图与身份/取消计划；R24水位与请求关联、R25真实对象codec、R28通知事务；R31显式稀疏事件消费/通知重投/远端ACK合成联调、无通知日期检查点及v5首事件前Order描述端口 | config/Store/Broker/Feed完整装配、submit/cancel与本地Submitted/Rejected耐久通知、首事件前自动恢复、策略资金/持仓getter隔离、迟到费用及完整回归；E020/E023/E074/E077/E080仍开放 |'
t=t.replace(line,new_line);p.write_text(t,encoding='utf-8-sig')
p=root/'开发问题记录.md';t=p.read_text(encoding='utf-8-sig');t+=f'''\n\nR31限定收口：E075/E076/E078/E079及T018经过独立修后复核，最终BT源码/安装各984 passed/1 strict xfailed、SDK各382 passed；产品提交BT `{b}`、SDK `{s}`。E074/E077/E080仍OPEN；E081是已核对原HEAD的既有缺陷。T019镜像修复、原失败/中断及fixture版本保留；主代理Git核验初稿另遗漏两个CTP公开helper的repo归属，改按真实三个repo核对后1138个路径通过，初稿stderr仅工具输出。详见[第三十一轮审阅](archived/{report_name})。\n''';p.write_text(t,encoding='utf-8-sig')
p=root/'分轮合同冻结稿-2026-11-08.md';t=p.read_text(encoding='utf-8-sig');t+=f'''\n\nR31限定结果：相同BT65/SDK20测试文件源码/安装各984（另1 strict xfailed）/382 passed，已提交并[归档](archived/{report_name})。§33.2中阻止旧账户同步是完整模式的目标约束；本轮仅隔离事件next、写入口和reconcile队列，getcash/getvalue/getposition的旧刷新分支尚需E080在完整装配中解决，不能说整条读取路径已隔离。E074/E077与完整config/提交等缺口保持。\n''';p.write_text(t,encoding='utf-8-sig')
p=BT/'docs/source/developer-guide/repository-responsibilities_zh.md';t=p.read_text(encoding='utf-8-sig');pos=t.index('\n')+1;t=t[:pos]+f'''\n> 2026-11-09 R31：SDK `gateway_execution_time` 持有显式时间解释；BT `_btapi_gateway_stream` 持有真实事件到原Broker对象/原Strategy通知及ACK的显式适配，`gateway_order_state`在原pending v5保存首事件前单订单描述。源码/安装BT984（另1预期失败）/SDK382通过；config/submit/cancel与首次恢复、资金和旧读取隔离尚未交付，不是完整生产Gateway模式。[R31审阅](../../_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话/archived/{report_name})。\n'''+t[pos:];p.write_text(t,encoding='utf-8-sig')
print('Updated R31 report, baseline, matrix, issue record, contract and responsibilities')
