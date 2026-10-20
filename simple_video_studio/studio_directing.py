"""Opt-in performance beats and soundscapes, no remote prompt rewriting."""
AMBIENCES = {
    "none": ("自行描述", "", ""),
    "summer_street": ("夏日街边：蝉鸣与远车", "室外夏日晚间，树上较远的蝉鸣起伏成底声，远处轮胎声稀疏经过；路人模糊交谈退在远景，不出现可辨认台词。偶尔一声远处短促鸣笛，不要持续鸣笛。只有画外确有行人经过时才有几步轻微鞋底踩人行道声。环境声低于近景人物，不要背景音乐。", "A quiet summer neighborhood street. Distant cicadas ebb softly under sparse passing tire noise. Faint indistinct pedestrian chatter far away, no intelligible words. One brief distant car horn, restrained, no music or narration."),
    "night_street": ("夜间街道：轮胎与远处人声", "安静夜间街道，远处少量汽车轮胎经过，细微树叶沙沙声和很远的模糊路人交谈；不生成清晰人声、不增加蝉鸣，不要音乐。", "Quiet nighttime neighborhood street, sparse distant passing cars, a gentle rustle of leaves, very faint indistinct pedestrian murmur far away. No intelligible speech, no music, no cicadas."),
    "room": ("室内：房间底噪", "安静普通住宅的细微室内底噪，远处冰箱低鸣和极轻室外车声隔窗传入；保留人物呼吸和衣物细动，不增加可辨认台词、脚步或音乐。", "Quiet domestic room tone, faint distant refrigerator hum, very soft muffled traffic through a closed window. No intelligible speech, footsteps or music."),
    "cicadas": ("独立蝉鸣", "远处树冠的夏日蝉鸣自然起伏，不要鸟叫、车声、人声或音乐。", "Distant summer cicadas in trees, an organic gently fluctuating insect chorus, outdoor open air. No birds, traffic, speech or music."),
    "traffic": ("独立远处车流", "远处少量车辆轮胎经过，偶尔一声很短且更远的鸣笛；不加人声或音乐。", "Sparse distant traffic passing on asphalt, restrained tire noise with one short distant horn. No speech or music."),
    "crowd": ("独立远处人声", "远处零散路人低声交谈，听不清具体词句，不要清晰台词、笑声大起或音乐。", "Very distant indistinct pedestrian conversation, a low diffuse murmur without any intelligible words, no foreground voices or music."),
    "footsteps": ("画外路人脚步（需校准）", "画外一位路人穿平底鞋以正常步频走过水泥人行道，脚步从稍近渐远。不把它误当成静止主体的脚步，不加对白或音乐；后期按实际入点校准。", "An off-screen pedestrian in flat shoes walking across a concrete sidewalk at a normal pace, footsteps pass and recede, realistic sole contacts. No voices or music."),
    "leaves": ("独立轻风树叶", "微风轻吹树叶与细枝的低声沙沙起伏，远近自然，不是大风呼啸，不加音乐或人声。", "Soft irregular leaf rustles in a gentle breeze, delicate foliage movement in open air, no strong wind gusts, speech or music."),
}

PERFORMANCES = {
    "none": ("按原提示词，不追加表演", ""),
    "listen": ("听见后反应：眼神 → 表情", "只对用户指定的主要近景人物增加一个克制的反应节拍：先注视原有目标，听见附近声音后眼球先转向声源，随后头部小幅跟随，短暂停顿理解，再回到原注视方向；嘴角与眉部有轻微不同步变化，伴随自然呼吸和一次自然眨眼。不要所有人同时眨眼，不强迫夸张微笑；用户原有台词、动作和情绪优先。"),
    "selfie": ("自拍微表演：观察 → 放松", "主要自拍人物先看手机镜头，随后短暂查看屏幕中的自己，轻轻呼气、放松下颌，嘴角产生细小的不对称变化，再回到镜头。头部只做几度的轻微调整，眨眼与眼神变化错开；不要持续瞪眼或固定微笑。拍摄手机保持在画面外，不新增第二部手机。用户原有动作和情绪优先。"),
}


def soundscape(data):
    custom = str(data.get("soundscape") or "").strip()
    preset = str(data.get("ambience") or "none")
    if preset not in AMBIENCES:
        raise ValueError("未知环境声预设")
    return custom or AMBIENCES[preset][1]


def performance(data):
    key = str(data.get("performance") or "none")
    if key not in PERFORMANCES:
        raise ValueError("未知表演预设")
    beat = PERFORMANCES[key][1]
    if beat:
        beat += "没有台词的阶段嘴唇自然闭合，呼吸通过鼻腔表现，不随意张嘴、噘嘴或做口型；明确说话的阶段按用户原有台词表演。"
    return beat
