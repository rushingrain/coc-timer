# coc-timer
fan-made tool for Clash of Clans

一个使用 FastAPI、Jinja2 和 HTMX 的部落冲突完成时间计算器。可以同时记录 6 个建筑工人、1 个技能研究和 1 个战宠研究，并按 8 种加速道具计算预计结束时刻。

## 环境安装（首次）

需要 Python 3.11 或更新版本。在项目根目录创建虚拟环境并安装依赖：

    python3 -m venv .venv
    .venv/bin/python -m pip install -e .

虚拟环境会保留在 .venv 目录中。以后启动项目不需要重复执行上述命令；只有重建虚拟环境或项目依赖发生变化时，才需要重新安装。

## 日常启动与关闭

每次使用时，在项目根目录运行：

    .venv/bin/uvicorn app.main:app --reload

浏览器打开 http://127.0.0.1:8000 。开发模式下，修改代码会自动重载服务。使用结束后，在运行服务的终端按 Ctrl+C 即可关闭；下次只需再次执行上面的启动命令。关闭浏览器标签页不会停止服务。

数据库默认保存在项目目录下的 data/coc_timer.sqlite3，停止服务不会清除已录入的数据；可以通过环境变量 COC_TIMER_DB 指定其他路径。

## 云服务器部署（Ubuntu/Debian + systemd）

推荐把代码放在 /opt/coc-timer，把数据库放在 /var/lib/coc-timer/coc_timer.sqlite3。两者分开后，更新代码或重建虚拟环境不会影响数据库。仓库提供了 [生产启动脚本](deploy/start.sh) 和 [systemd 服务配置](deploy/coc-timer.service)；如果采用其他代码目录，需要同步修改这两个文件中的绝对路径。

先将项目源码部署到 /opt/coc-timer，确保部署账号对代码目录有写权限、服务用户对目录和虚拟环境有读取及执行权限，并确认服务器的 Python 不低于 3.11。虚拟环境需要在服务器上重新创建，不要复制本地的 .venv。然后执行：

    cd /opt/coc-timer
    python3 -m venv .venv
    .venv/bin/python -m pip install -e .
    sudo install -m 644 deploy/coc-timer.service /etc/systemd/system/coc-timer.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now coc-timer

systemd 会自动创建服务所需的数据目录，并在开机时启动服务。生产启动脚本使用单个 Uvicorn 进程、监听所有网卡的 8000 端口，不使用开发模式的自动重载。服务器和云平台防火墙放行 TCP 8000 后，可以通过公网 IP 加端口访问。当前单人版本尚无登录功能，建议在云平台安全组中把 8000 的来源限制为自己的 IP；如需长期公开访问，应先加入认证与 HTTPS。

日常管理与检查：

    systemctl is-active coc-timer                 # 快速查看是否运行，正常输出 active
    systemctl status coc-timer --no-pager         # 查看进程状态和最近日志
    sudo ss -lntp | grep ':8000'                  # 确认监听地址为 0.0.0.0:8000
    curl -fsS http://127.0.0.1:8000/healthz       # 检查应用和数据库是否可访问
    sudo systemctl restart coc-timer              # 更新代码后重启
    sudo systemctl stop coc-timer                 # 停止服务
    sudo systemctl start coc-timer                # 再次启动
    journalctl -u coc-timer -n 100 --no-pager     # 查看最近 100 行日志
    journalctl -u coc-timer -f                    # 实时跟踪日志

若修改了服务配置文件，需重新执行 sudo install -m 644 deploy/coc-timer.service /etc/systemd/system/coc-timer.service 和 sudo systemctl daemon-reload，再重启服务。若修改了项目依赖，先在服务器运行 .venv/bin/python -m pip install -e .，再重启服务。

如果本机健康检查成功但公网仍不可达，先确认服务器上已更新 deploy/start.sh 并执行 sudo systemctl restart coc-timer，再检查监听地址和云平台安全组。若公网请求返回 HTTP 502，说明请求可能经过云平台网关或客户端代理；可从另一台机器使用 curl --noproxy '*' -i http://公网IP:8000/healthz 排查实际响应来源。

## 使用方法

1. 如果游戏中已有加速生效，先在“加速道具”区选择“同步游戏中已生效的道具”，填写其当前剩余生效分钟和秒数。
2. 在对应位置输入游戏当前显示的剩余倒计时（天、小时、分钟、秒），点击“计算完成时间”。录入时刻由服务器记录；页面显示北京时间和实时倒计时。
3. 之后新使用道具时，尽快在页面选择“现在使用一份”。同一种道具再次使用会延长 1 小时；不同道具会覆盖相同位置的当前加速，先前效果不恢复。
4. 如果加速记录有误，可停止记录当前加速，再按游戏中的实际状态同步加速并重新录入受影响位置的倒计时。

建筑道具同时影响 6 个工人；研究浓汤同时影响技能和战宠，研究药水与战宠药水各只影响自己的位置。互不重叠的位置独立计时。刷新页面后任务和加速记录仍在。

建筑工人区域点击“按完成时刻排序”后，会根据当前预计完成时间重新排列并将工人顺序保存到数据库。录入或修改任务时间不会改变已保存的顺序；需要更新排序时再次点击按钮即可。清空某个工人的任务不会丢失其顺序位置。

卡片中的“还需”为距离预计完成时刻的真实等待时间。下方录入时间旁的“游戏显示时间”动态计算游戏倒计时：无加速时正常递减，有加速时按记录的倍率递减，道具到期后恢复正常速度。时间按天、小时、分钟显示，数字与中文之间使用空格，例如“2 天 3 小时 15 分钟”；省略为零的单位和秒数，剩余时间大于零但不足一分钟时显示“1 分钟”，完成后显示“已完成”。

卡片顶部栏会在状态标签左侧显示完成提醒，统一按北京时间判断：任何日期的 23:00（含）至次日 07:00（不含）显示红色“夜间完成”；今天 07:00（含）至 23:00（不含）显示绿色“今日完成”。其他日期的白天、空位置和已完成任务不显示提醒。页面跨天或应用加速后会自动更新标识，任务完成后自动隐藏。

当前版本面向本地单人使用，只提供计算，不发送提醒。HTMX 从 CDN 加载；无法加载时，表单仍可通过普通页面刷新提交。未来如公开部署，需要增加用户身份与独立数据隔离；QQ 提醒的扩展思路见 [实施方案](docs/implementation-plan.md)。
