# 第五期“可确认的连续语音面试模式”发布报告

## 交付范围

- 新增纯前端 ContinuousVoiceSessionController，以 generation fencing 管理朗读、等待开口、VAD 候选结束、倒计时、停止、转写、人工确认、回答提交和下一题。
- VoiceAnswerComposer 增加受控语音意图，继续复用现有 TTS、MediaRecorder、VAD、浏览器识别和离线 Whisper；媒体阶段不发业务请求，只有确认文字后才进入原有回答 API。
- Interview Studio 接入连续模式，保留标准文字/语音模式、证据栏、追问引用、幂等 key、结果未知重试和人工确认语义。
- 补强 pending getUserMedia、TTS、MediaRecorder onstop、页面隐藏、组件卸载、重录、转写及 StrictMode 的资源清理和代际隔离。
- 结果未知时把 Attempt、时间线、原始 operation key 和状态写入 sessionStorage，重新打开 Studio 可使用原 key 恢复；连续语音的表达复盘快照也会在确认后沿用原保存链路。
- Studio 回答区在宽窄屏使用紧凑 Surface；Haru 的普通页尺寸、状态提示和 Studio 位置继续分离，默认位置受安全区约束。

## 破坏性变化

无。没有数据库迁移、公开 API 或后端领域模型变化；没有修改现有 Mock Interview、Voice Coaching、HITL、lease/CAS/fencing、202、结果未知和历史只读语义。

## 浏览器验收

使用中文候选人“筱哲”、亮色主题完成真实投递 Studio 流程：

- 明确选择投递、面试事件、JD 和简历后才进入 Studio。
- 首题展示 JD、简历路径和逐字摘录；追问展示“上一轮回答 → 当前追问”关联。
- 连续语音需用户主动开启；当前 in-app browser 的麦克风 getUserMedia 保持 pending，因此验证了可退出预检并回到标准模式，未伪造真实录音成功。
- 标准文字回答完成提交、证据化追问和复盘建议生成闭环；Haru 默认位置及拖动后位置均未遮挡内容。
- 1440×900：documentScrollWidth=1440、bodyScrollWidth=1440。
- 390×844：documentScrollWidth=390、bodyScrollWidth=390、Studio scrollWidth=390，无横向溢出。

截图目录：[artifacts/continuous-voice-interview](../../../artifacts/continuous-voice-interview/)

- [准备中心](../../../artifacts/continuous-voice-interview/01-preparation-1440x900-light-xizhe.png)
- [首题与证据](../../../artifacts/continuous-voice-interview/02-first-question-1440x900-light-xizhe.png)
- [连续语音预检](../../../artifacts/continuous-voice-interview/03-continuous-voice-preflight-1440x900-light-xizhe.png)
- [追问证据](../../../artifacts/continuous-voice-interview/04-evidence-followup-1440x900-light-xizhe.png)
- [完成复盘](../../../artifacts/continuous-voice-interview/05-completed-review-1440x900-light-xizhe.png)
- [Haru 拖动](../../../artifacts/continuous-voice-interview/06-haru-drag-1440x900-light-xizhe.png)
- [窄屏准备中心](../../../artifacts/continuous-voice-interview/07-preparation-390x844-light-xizhe.png)
- [窄屏 Studio](../../../artifacts/continuous-voice-interview/08-studio-390x844-light-xizhe.png)

## 验证结果

- npm.cmd test -- --run src/features --reporter=dot：41 个文件、298 个测试通过。
- 定向连续语音/Studio/Haru：6 个文件、72 个测试通过；其中包含 business result-unknown 原 key 恢复、连续 voice review 保存和资源 fencing。
- npm.cmd run build：通过。
- 前端分组门禁此前累计 164 个文件、1182 个测试通过。
- uv run ruff check .、uv run mypy src、uv run oc smoke --static-dir web/dist：通过。
- 后端分组门禁：domain 73/73、proposals 431/431、knowledge 659（含 4 个允许跳过）、agent 454/454；misc 485 个通过、1 个因缺失外部 OFFERPILOT_APPLICATION_JD_BASELINE_FILE 的 JD Harness 环境变量失败。该失败属于外部基线环境，不是本次连续语音改动。
- 首次定向 pytest 无输出超过 60 秒时已检查并清理进程；有效分组收集约 14.8 秒，未将初始化问题误判为产品失败。
- 独立代码复审曾发现的 P1/P2 已逐项修复并由定向测试、构建和特定场景复核覆盖；未发现 P0。

## 剩余风险

- 当前浏览器环境没有可用的麦克风授权，无法在真实浏览器中完成实际 MediaRecorder/VAD/离线 Whisper 成功路径；该路径由控制器、Composer 和恢复边界测试覆盖，浏览器中已验证安全降级。
- JD Harness 仍需在正式发布环境补齐外部基线文件后重新执行。
- 本分支不推送、不合并，等待用户审核。
