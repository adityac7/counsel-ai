"""Case studies bank for Indian class 9-12 students."""

from __future__ import annotations

# Category → 2-letter ID prefix (must stay in sync with the dashboard form)
CATEGORY_PREFIXES: dict[str, str] = {
    "Ethical Dilemmas": "ED",
    "Social Pressure": "SP",
    "Family Conflicts": "FC",
    "Digital Ethics": "DE",
    "Achievement Pressure": "AP",
    "Leadership": "LD",
}

CASE_STUDIES = [
    {
        "id": "ED-01",
        "title": "Answer Sheet Whispers",
        "category": "Ethical Dilemmas",
        "target_class": "8-10",
        "scenario_text": (
            "Rahul and Vivek have been friends since class 6, sharing lunch and coaching notes. "
            "During the class 10 pre-board, Rahul notices Vivek trying to peek at his answer sheet. "
            "The invigilator, Mrs. Dutta, is strict but trusts Rahul because he always follows rules.\n\n"
            "After the exam, Vivek laughs it off and says, 'Bro, one mark doesn't matter. You're "
            "my only safe side.' He hints that everyone does it, and Rahul feels torn because he "
            "doesn't want to be the reason his friend fails. At the same time, he feels guilty about "
            "helping someone cheat.\n\n"
            "The next day, Mrs. Dutta privately asks Rahul if anything happened during the exam. "
            "Rahul knows that if he tells the truth, Vivek could be barred. If he lies, he feels he is "
            "betraying his own values and his teacher's trust. The board exams are close, and the class "
            "is already under pressure."
        ),
        "scenario_text_hi": (
            "Rahul और Vivek क्लास 6 से दोस्त हैं — साथ में लंच करते हैं, कोचिंग के नोट्स शेयर करते हैं। "
            "क्लास 10 के प्री-बोर्ड एग्ज़ाम में Rahul को दिखता है कि Vivek उसकी आंसर शीट में झाँकने की "
            "कोशिश कर रहा है। इन्विजिलेटर Mrs. Dutta बहुत स्ट्रिक्ट हैं, लेकिन उन्हें Rahul पर भरोसा है "
            "क्योंकि वो हमेशा रूल्स फॉलो करता है।\n\n"
            "एग्ज़ाम के बाद Vivek हँसकर बोलता है, 'यार, एक मार्क से क्या फ़र्क पड़ता है। तू ही मेरा सहारा "
            "है।' वो कहता है कि सब लोग ऐसा करते हैं। Rahul कन्फ्यूज़ है — वो नहीं चाहता कि उसकी वजह से "
            "उसका दोस्त फेल हो। लेकिन साथ ही उसे नकल में मदद करने पर गिल्ट भी हो रहा है।\n\n"
            "अगले दिन Mrs. Dutta Rahul को अलग बुलाकर पूछती हैं कि एग्ज़ाम में कुछ हुआ था क्या। Rahul "
            "जानता है कि अगर वो सच बोले तो Vivek पर एक्शन हो सकता है। और अगर झूठ बोले तो वो अपनी "
            "वैल्यूज़ और टीचर के भरोसे को तोड़ रहा है। बोर्ड एग्ज़ाम करीब हैं और पूरी क्लास पहले से "
            "प्रेशर में है।"
        ),
        "probing_angles": [
            "What does being a good friend mean to Rahul in this moment?",
            "How does Rahul weigh fairness to other students against loyalty to Vivek?",
            "What are Rahul's fears about the consequences, and are they realistic?",
            "If Rahul stays silent now, how might it affect his self-image later?",
        ],
    },
    {
        "id": "ED-02",
        "title": "Project Credit Mix-up",
        "category": "Ethical Dilemmas",
        "target_class": "11-12",
        "scenario_text": (
            "Priya and Arjun are in class 11 and working on a group physics project. Priya writes the "
            "report and designs the charts, while Arjun is supposed to do the data analysis. On the day "
            "before submission, Arjun hasn't finished, so Priya stays up late to do his part as well.\n\n"
            "At the presentation, Arjun speaks confidently and the teacher praises the team. Later, a "
            "senior asks Priya for help with her own project, assuming Arjun did the analysis. Priya "
            "feels invisible but worries that correcting the record will create tension in the group and "
            "harm her reputation as a 'team player.'\n\n"
            "Arjun casually says, 'This is how it is in groups, yaar. Next time I'll cover.' Priya feels "
            "hurt and wonders whether she should raise the issue with the teacher or keep quiet to avoid "
            "being labeled difficult in class 11."
        ),
        "scenario_text_hi": (
            "Priya और Arjun क्लास 11 में हैं और एक ग्रुप फिज़िक्स प्रोजेक्ट पर काम कर रहे हैं। Priya "
            "रिपोर्ट लिखती है और चार्ट्स बनाती है, जबकि Arjun को डेटा एनालिसिस करना है। सबमिशन से एक "
            "दिन पहले Arjun का काम अभी तक पूरा नहीं हुआ है, तो Priya रात में जागकर उसका पार्ट भी खुद "
            "कर लेती है।\n\n"
            "प्रेज़ेंटेशन में Arjun कॉन्फ़िडेंटली बोलता है और टीचर पूरी टीम की तारीफ़ करते हैं। बाद में "
            "एक सीनियर Priya से मदद माँगती है अपने प्रोजेक्ट के लिए, ये सोचकर कि एनालिसिस Arjun ने "
            "किया है। Priya को लगता है कि उसकी मेहनत किसी को दिखी ही नहीं, लेकिन वो डरती है कि अगर "
            "बात उठाई तो ग्रुप में टेंशन होगी और लोग उसे 'टीम प्लेयर' नहीं समझेंगे।\n\n"
            "Arjun आराम से बोलता है, 'ग्रुप में ऐसा ही होता है यार। अगली बार मैं कवर कर लूँगा।' Priya "
            "को बुरा लगता है और वो सोचती है कि टीचर से बात करे या चुप रहे ताकि क्लास 11 में उसे "
            "'मुश्किल लड़की' का टैग न लगे।"
        ),
        "probing_angles": [
            "What does Priya want recognition for, and why does it matter to her?",
            "How might she communicate boundaries without breaking the group?",
            "What long-term pattern could form if she stays silent now?",
            "How does Priya define fairness in collaboration?",
        ],
    },
    {
        "id": "SP-01",
        "title": "The New Kid Target",
        "category": "Social Pressure",
        "target_class": "8-10",
        "scenario_text": (
            "A new student, Ishan, joins class 9 mid-term. He is quiet, speaks with a different accent, "
            "and often eats alone in the canteen. A popular group led by Meera starts making jokes about "
            "his lunch and calling him 'gaon ka.'\n\n"
            "Riya is part of Meera's group and is expected to laugh along. She doesn't like the teasing, "
            "but she is scared of being left out if she says anything. Everyone in class seems to be "
            "watching who stands with the group.\n\n"
            "One day the group plans to hide Ishan's bag during sports period. They tell Riya, 'You have "
            "to do it, otherwise you are not one of us.' Riya's stomach tightens as she thinks about what "
            "to do."
        ),
        "scenario_text_hi": (
            "एक नया स्टूडेंट Ishan, क्लास 9 में बीच टर्म में आता है। वो शांत रहता है, उसका एक्सेंट "
            "अलग है, और वो अक्सर कैंटीन में अकेला खाना खाता है। Meera के पॉपुलर ग्रुप ने उसके लंच पर "
            "मज़ाक उड़ाना शुरू कर दिया है और उसे 'गाँव का' बुलाते हैं।\n\n"
            "Riya Meera के ग्रुप में है और उसे भी साथ में हँसना पड़ता है। उसे ये छेड़छाड़ पसंद नहीं है, "
            "लेकिन वो डरती है कि अगर कुछ बोली तो ग्रुप से बाहर कर दी जाएगी। पूरी क्लास देख रही है कि "
            "कौन किसके साथ खड़ा है।\n\n"
            "एक दिन ग्रुप स्पोर्ट्स पीरियड में Ishan का बैग छुपाने का प्लान बनाता है। वो Riya से कहते "
            "हैं, 'तुझे ये करना पड़ेगा, वरना तू हमारी नहीं है।' Riya का पेट कसने लगता है — वो सोचती है "
            "कि अब क्या करे।"
        ),
        "probing_angles": [
            "What does belonging mean to Riya, and what is she afraid to lose?",
            "How does Riya justify or challenge the group's behavior?",
            "What might happen if she chooses a small act of support for Ishan?",
            "How does peer approval shape her decisions in other areas?",
        ],
    },
    {
        "id": "SP-02",
        "title": "The Viral Dare",
        "category": "Social Pressure",
        "target_class": "11-12",
        "scenario_text": (
            "Kabir is in class 12 and his friend group loves doing viral reels. They are planning a "
            "challenge video in the school corridor, which includes jumping over the staircase rail. "
            "Kabir feels it's risky and against school rules, but his friends say it will get them "
            "thousands of views.\n\n"
            "His close friend Sameer tells him, 'If you don't do it, you are boring. We need you for the "
            "final shot.' Kabir doesn't want to be seen as cowardly, and he is worried he will lose their "
            "friendship in the last year of school.\n\n"
            "He also knows the principal has warned about such stunts, and getting caught could affect "
            "their board records and even their farewell. Kabir is stuck between safety, rules, and the "
            "need for social acceptance."
        ),
        "scenario_text_hi": (
            "Kabir क्लास 12 में है और उसका फ्रेंड ग्रुप वायरल रील्स बनाने का शौकीन है। वो स्कूल के "
            "कॉरिडोर में एक चैलेंज वीडियो प्लान कर रहे हैं जिसमें सीढ़ी की रेलिंग के ऊपर से कूदना है। "
            "Kabir को लगता है कि ये रिस्की है और स्कूल के रूल्स के खिलाफ़ है, लेकिन उसके दोस्त कहते हैं "
            "कि हज़ारों व्यूज़ आएँगे।\n\n"
            "उसका करीबी दोस्त Sameer बोलता है, 'अगर तूने नहीं किया तो तू बोरिंग है। फाइनल शॉट में तू "
            "चाहिए।' Kabir नहीं चाहता कि उसे डरपोक समझा जाए, और उसे डर है कि स्कूल के लास्ट साल में "
            "दोस्ती टूट जाएगी।\n\n"
            "उसे ये भी पता है कि प्रिंसिपल ने ऐसे स्टंट्स की वॉर्निंग दी है, और पकड़े जाने पर बोर्ड "
            "रिकॉर्ड और फेयरवेल तक पर असर पड़ सकता है। Kabir सेफ्टी, रूल्स और दोस्तों की एक्सेप्टेंस "
            "के बीच फँसा हुआ है।"
        ),
        "probing_angles": [
            "How does Kabir balance short-term approval with long-term consequences?",
            "What does he fear more: losing friends or getting hurt?",
            "How might he express his discomfort without losing status?",
            "What past experiences shape his response to peer pressure?",
        ],
    },
    {
        "id": "FC-01",
        "title": "Science at Home, Art in Heart",
        "category": "Family Conflicts",
        "target_class": "8-10",
        "scenario_text": (
            "Ananya is in class 10 and spends her evenings sketching and designing posters. She recently "
            "won an inter-school art competition. Her parents, however, are focused on board results and "
            "want her to take Science in class 11 because her cousin became an engineer.\n\n"
            "The subject choice form is due in two weeks. At dinner, her father says, 'Arts is a hobby, "
            "not a career.' Her mother adds that in their community, Science is seen as the 'safe' option. "
            "Ananya feels unheard and also guilty for disappointing her parents who work hard.\n\n"
            "Her class teacher asks students to finalize streams soon. Ananya feels torn between her own "
            "dreams and the fear of losing her parents' approval."
        ),
        "scenario_text_hi": (
            "Ananya क्लास 10 में है और शाम को स्केचिंग और पोस्टर डिज़ाइन करती है। हाल ही में उसने "
            "इंटर-स्कूल आर्ट कम्पटीशन जीता है। लेकिन उसके पैरेंट्स बोर्ड रिज़ल्ट पर फ़ोकस हैं और चाहते "
            "हैं कि वो क्लास 11 में साइंस ले, क्योंकि उनके भतीजे ने इंजीनियरिंग की है।\n\n"
            "सब्जेक्ट चुनने का फॉर्म दो हफ़्तों में भरना है। डिनर पर उसके पापा कहते हैं, 'आर्ट्स शौक "
            "है, करियर नहीं।' मम्मी कहती हैं कि उनकी कम्युनिटी में साइंस को 'सेफ' ऑप्शन माना जाता "
            "है। Ananya को लगता है कि कोई उसकी बात नहीं सुन रहा, और साथ ही उसे गिल्ट भी है कि वो "
            "मेहनती पैरेंट्स को निराश कर रही है।\n\n"
            "क्लास टीचर कहती हैं कि जल्दी स्ट्रीम फ़ाइनल करो। Ananya अपने सपनों और पैरेंट्स की मंज़ूरी "
            "खोने के डर के बीच फँसी हुई है।"
        ),
        "probing_angles": [
            "What does Ananya feel responsible for in her family?",
            "How does she define success for herself versus her parents' definition?",
            "What compromises or conversations could she imagine?",
            "How might her fear of conflict shape her decision?",
        ],
    },
    {
        "id": "FC-02",
        "title": "Commerce or Coaching?",
        "category": "Family Conflicts",
        "target_class": "11-12",
        "scenario_text": (
            "Dev is in class 11 and wants to switch from Science to Commerce after realizing he struggles "
            "with Physics. His father has already paid for JEE coaching and tells him, 'We have invested, "
            "you cannot change now.'\n\n"
            "At home, conversations quickly become arguments. Dev's mother asks him to adjust because "
            "they are worried about relatives' opinions. Dev feels his parents care more about reputation "
            "than his mental health.\n\n"
            "His marks are dropping, and he is anxious before every test. He wonders if he should keep "
            "quiet and push through, or speak up and risk more conflict at home."
        ),
        "scenario_text_hi": (
            "Dev क्लास 11 में है और साइंस से कॉमर्स में जाना चाहता है क्योंकि उसे फिज़िक्स में बहुत "
            "दिक्कत हो रही है। उसके पापा पहले ही JEE कोचिंग की फ़ीस भर चुके हैं और कहते हैं, 'हमने "
            "इन्वेस्ट किया है, अब बदल नहीं सकते।'\n\n"
            "घर पर बातचीत जल्दी बहस में बदल जाती है। Dev की मम्मी कहती हैं कि एडजस्ट कर लो क्योंकि "
            "रिश्तेदार क्या कहेंगे। Dev को लगता है कि उसके पैरेंट्स को उसकी मेंटल हेल्थ से ज़्यादा "
            "इज़्ज़त की चिंता है।\n\n"
            "उसके मार्क्स गिर रहे हैं और हर टेस्ट से पहले उसे बहुत एंग्ज़ाइटी होती है। वो सोचता है कि "
            "चुप रहकर किसी तरह निकाले या बोले और घर में और झगड़ा हो।"
        ),
        "probing_angles": [
            "What emotions come up for Dev when his parents mention investment and reputation?",
            "How does fear of disappointment affect his honesty at home?",
            "What might be a respectful way for him to express his limits?",
            "How does Dev imagine his future in both streams?",
        ],
    },
    {
        "id": "DE-01",
        "title": "Forwarded Without Thinking",
        "category": "Digital Ethics",
        "target_class": "8-10",
        "scenario_text": (
            "Sana is in class 9 and part of a WhatsApp group for her section. One evening, someone posts a "
            "private photo of a classmate, Neha, taken from her Instagram story. The caption is mocking, "
            "and emojis flood the chat.\n\n"
            "Sana feels uncomfortable but everyone is forwarding the image to other groups. One friend "
            "says, 'It's just a joke, don't be so serious.' Sana knows Neha has been sensitive about her "
            "appearance and recently skipped school.\n\n"
            "Sana debates whether to say something in the group, message Neha privately, or ignore it. She "
            "fears being targeted if she speaks up."
        ),
        "scenario_text_hi": (
            "Sana क्लास 9 में है और अपने सेक्शन के WhatsApp ग्रुप में है। एक शाम किसी ने क्लासमेट "
            "Neha की एक प्राइवेट फ़ोटो डाल दी जो उसकी Instagram स्टोरी से ली गई थी। कैप्शन मज़ाक "
            "उड़ाने वाला है और चैट में इमोजी की बाढ़ आ गई है।\n\n"
            "Sana को अनकम्फ़र्टेबल लग रहा है लेकिन सब लोग इमेज दूसरे ग्रुप्स में फ़ॉरवर्ड कर रहे हैं। "
            "एक फ्रेंड बोलती है, 'बस मज़ाक है, इतना सीरियस मत हो।' Sana को पता है कि Neha अपनी "
            "अपीयरेंस को लेकर सेंसिटिव है और हाल ही में स्कूल भी नहीं आई थी।\n\n"
            "Sana सोच रही है कि ग्रुप में कुछ बोले, Neha को प्राइवेटली मैसेज करे, या बस इग्नोर कर दे। "
            "उसे डर है कि अगर बोली तो अगला निशाना वो होगी।"
        ),
        "probing_angles": [
            "What does Sana feel responsible for in a digital space?",
            "How does fear of backlash affect her choices?",
            "What could be a small step to reduce harm?",
            "How might Sana feel if the same happened to her?",
        ],
    },
    {
        "id": "DE-02",
        "title": "Cheat Sheet PDF",
        "category": "Digital Ethics",
        "target_class": "11-12",
        "scenario_text": (
            "Arjun is in class 12 and part of a Telegram group where seniors share study material. A file "
            "appears with 'Important Board Answers' and a note saying it's leaked from the school office. "
            "Many classmates start downloading it.\n\n"
            "Arjun feels the temptation because he is worried about his Physics board. At the same time, "
            "he knows it is unfair and risky. If the school finds out, the whole class could face serious "
            "consequences.\n\n"
            "His friend Nikhil insists, 'Everyone is doing it; if you don't, you will fall behind.' Arjun "
            "wonders whether staying honest will make him look foolish or whether taking the file will make "
            "him feel guilty later."
        ),
        "scenario_text_hi": (
            "Arjun क्लास 12 में है और एक Telegram ग्रुप में है जहाँ सीनियर्स स्टडी मटीरियल शेयर करते "
            "हैं। एक फ़ाइल आती है जिस पर लिखा है 'Important Board Answers' और नोट है कि ये स्कूल "
            "ऑफ़िस से लीक हुई है। बहुत सारे क्लासमेट्स उसे डाउनलोड करने लगते हैं।\n\n"
            "Arjun को भी लालच हो रहा है क्योंकि उसे फिज़िक्स बोर्ड की चिंता है। लेकिन साथ ही उसे पता "
            "है कि ये ग़लत है और रिस्की भी। अगर स्कूल को पता चला तो पूरी क्लास पर सीरियस एक्शन हो "
            "सकता है।\n\n"
            "उसका दोस्त Nikhil ज़ोर देकर कहता है, 'सब कर रहे हैं; अगर तूने नहीं किया तो पीछे रह "
            "जाएगा।' Arjun सोचता है कि ईमानदार रहने से वो बेवकूफ़ लगेगा या फ़ाइल लेने से बाद में "
            "गिल्ट होगा।"
        ),
        "probing_angles": [
            "How does Arjun handle competition and fear of falling behind?",
            "What principles does he want to uphold, even under pressure?",
            "How might he talk to friends without seeming judgmental?",
            "What does he think about collective consequences for the class?",
        ],
    },
    {
        "id": "AP-01",
        "title": "Seventy Percent Silence",
        "category": "Achievement Pressure",
        "target_class": "8-10",
        "scenario_text": (
            "Rohit gets 70% in his class 10 pre-boards. At home, his parents are disappointed and compare "
            "him to his cousin who scored 95%. They say things like, 'We expected better from you.' Rohit "
            "feels ashamed and avoids speaking at dinner.\n\n"
            "In school, his best friend Aman confides that he is thinking about self-harm after getting 95% "
            "but still feeling he failed. Rohit is shocked because Aman always looks confident. He feels "
            "helpless and worried about saying the wrong thing.\n\n"
            "Rohit wonders how to handle his parents' pressure while also being present for his friend. He "
            "feels like no one sees how stressed he is."
        ),
        "scenario_text_hi": (
            "Rohit के क्लास 10 के प्री-बोर्ड में 70% आते हैं। घर पर उसके पैरेंट्स निराश हैं और उसकी "
            "तुलना उसके कज़िन से करते हैं जिसके 95% आए। वो कहते हैं, 'हमें तुमसे बेहतर की उम्मीद थी।' "
            "Rohit को शर्म आती है और डिनर पर वो बात करने से बचता है।\n\n"
            "स्कूल में उसका सबसे अच्छा दोस्त Aman बताता है कि 95% आने के बावजूद उसे लगता है कि वो "
            "फेल हो गया, और वो सेल्फ़-हार्म के बारे में सोच रहा है। Rohit को शॉक लगता है क्योंकि Aman "
            "हमेशा कॉन्फ़िडेंट दिखता है। Rohit बेबस महसूस करता है और डरता है कि कहीं ग़लत बात न बोल "
            "दे।\n\n"
            "Rohit समझ नहीं पा रहा कि पैरेंट्स का प्रेशर कैसे सँभाले और साथ ही अपने दोस्त के लिए कैसे "
            "मौजूद रहे। उसे लगता है कि कोई नहीं देख रहा कि वो कितना स्ट्रेस में है।"
        ),
        "probing_angles": [
            "What messages has Rohit internalized about marks and self-worth?",
            "How does he manage his own stress while supporting Aman?",
            "What might he want to say to his parents but holds back?",
            "What are safe, responsible steps when a friend mentions self-harm?",
        ],
    },
    {
        "id": "AP-02",
        "title": "Topper Expectations",
        "category": "Achievement Pressure",
        "target_class": "11-12",
        "scenario_text": (
            "Nisha has always been a topper and her teachers expect her to score above 95% in class 12. "
            "Recently, her marks have slipped to around 85% because she is also preparing for a state-level "
            "dance competition.\n\n"
            "Her parents are proud of her dance but keep reminding her that board marks are 'more important.' "
            "At school, teachers mention her in front of the class, saying, 'We expect you to set an example.' "
            "Nisha feels anxious and cannot sleep well before tests.\n\n"
            "She starts hiding her dance practice to avoid conflicts. She wonders if she should drop dance to "
            "keep her grades high or risk disappointing everyone."
        ),
        "scenario_text_hi": (
            "Nisha हमेशा से टॉपर रही है और उसके टीचर्स उम्मीद करते हैं कि वो क्लास 12 में 95% से ऊपर "
            "लाए। हाल ही में उसके मार्क्स 85% के आसपास आ गए हैं क्योंकि वो स्टेट-लेवल डांस कम्पटीशन "
            "की तैयारी भी कर रही है।\n\n"
            "उसके पैरेंट्स को उसके डांस पर गर्व है लेकिन बार-बार याद दिलाते हैं कि बोर्ड के मार्क्स "
            "'ज़्यादा ज़रूरी' हैं। स्कूल में टीचर्स क्लास के सामने कहते हैं, 'हम उम्मीद करते हैं कि तुम "
            "एक उदाहरण बनो।' Nisha को एंग्ज़ाइटी होती है और टेस्ट से पहले उसकी नींद ठीक से नहीं "
            "आती।\n\n"
            "वो अपनी डांस प्रैक्टिस छुपाने लगती है ताकि कोई इश्यू न हो। वो सोचती है कि ग्रेड्स बचाने "
            "के लिए डांस छोड़ दे या सबको निराश करने का रिस्क ले।"
        ),
        "probing_angles": [
            "How does Nisha handle being seen as the 'topper' by others?",
            "What does dance give her that academics do not?",
            "How does she experience anxiety in her body and mind?",
            "What boundaries could she set with teachers and parents?",
        ],
    },
    {
        "id": "LD-01",
        "title": "Cricket Ground Clash",
        "category": "Leadership",
        "target_class": "8-10",
        "scenario_text": (
            "Karan is the class 9 monitor and is known for being fair. Two groups in his class are fighting "
            "over the cricket ground during lunch. One group says they booked it first, while the other says "
            "they always play on Wednesdays.\n\n"
            "The sports teacher tells Karan to manage it because she is busy. Both groups are pressuring him "
            "to take their side. His best friend is in one group, and his cousin is in the other.\n\n"
            "Karan wants to keep peace but doesn't want to be seen as weak. He also worries that if he makes "
            "the wrong call, his classmates will stop respecting him."
        ),
        "scenario_text_hi": (
            "Karan क्लास 9 का मॉनिटर है और फ़ेयर होने के लिए जाना जाता है। उसकी क्लास के दो ग्रुप्स "
            "लंच में क्रिकेट ग्राउंड को लेकर लड़ रहे हैं। एक ग्रुप कहता है कि उन्होंने पहले बुक किया "
            "था, दूसरा ग्रुप कहता है कि बुधवार को हमेशा वो खेलते हैं।\n\n"
            "स्पोर्ट्स टीचर Karan से कहती हैं कि तुम मैनेज करो क्योंकि वो बिज़ी हैं। दोनों ग्रुप्स "
            "Karan पर प्रेशर डाल रहे हैं कि वो उनकी साइड ले। उसका बेस्ट फ्रेंड एक ग्रुप में है और "
            "कज़िन दूसरे में।\n\n"
            "Karan शांति बनाए रखना चाहता है लेकिन कमज़ोर भी नहीं दिखना चाहता। उसे डर है कि अगर ग़लत "
            "फ़ैसला लिया तो क्लासमेट्स उसकी इज़्ज़त करना बंद कर देंगे।"
        ),
        "probing_angles": [
            "What kind of leader does Karan want to be?",
            "How does he handle conflicts when personal relationships are involved?",
            "What fair process could he suggest?",
            "How might he deal with criticism after his decision?",
        ],
    },
    {
        "id": "LD-02",
        "title": "Prefect in the Middle",
        "category": "Leadership",
        "target_class": "11-12",
        "scenario_text": (
            "Shreya is a school prefect in class 12. Two house captains argue about allocating volunteers for "
            "the annual cultural fest. One house has more members but the other has been winning every year. "
            "Both want prime slots and accuse each other of favoritism.\n\n"
            "The principal tells Shreya to 'sort it out quietly.' She feels the pressure to keep staff happy "
            "while also being fair to students. Her friends expect her to support their house, and social "
            "media posts are already calling out bias.\n\n"
            "Shreya worries that any decision will upset someone. She wants to maintain integrity and also "
            "protect her reputation as a leader during her last year."
        ),
        "scenario_text_hi": (
            "Shreya क्लास 12 में स्कूल प्रीफ़ेक्ट है। दो हाउस कैप्टन सालाना कल्चरल फ़ेस्ट के लिए "
            "वॉलंटियर्स बाँटने पर बहस कर रहे हैं। एक हाउस में मेम्बर्स ज़्यादा हैं लेकिन दूसरा हाउस "
            "हर साल जीतता आया है। दोनों को बेस्ट स्लॉट चाहिए और दोनों एक-दूसरे पर फ़ेवरिटिज़्म का "
            "इल्ज़ाम लगा रहे हैं।\n\n"
            "प्रिंसिपल Shreya से कहते हैं, 'चुपचाप सुलझा लो।' उस पर प्रेशर है कि स्टाफ़ भी खुश रहे और "
            "स्टूडेंट्स के साथ फ़ेयर भी हो। उसके दोस्त चाहते हैं कि वो उनके हाउस को सपोर्ट करे, और "
            "सोशल मीडिया पर पहले से बायस की बात हो रही है।\n\n"
            "Shreya को चिंता है कि कोई भी फ़ैसला किसी न किसी को नाराज़ करेगा। वो अपनी इंटीग्रिटी बनाए "
            "रखना चाहती है और अपने लास्ट ईयर में लीडर के तौर पर अपनी इमेज भी बचाना चाहती है।"
        ),
        "probing_angles": [
            "What values guide Shreya's decision-making as a leader?",
            "How does she respond to public criticism and social media pressure?",
            "What communication style could reduce conflict?",
            "How might she separate her role from her personal friendships?",
        ],
    },
    {
        "id": "ED-03",
        "title": "Attendance Signature",
        "category": "Ethical Dilemmas",
        "target_class": "11-12",
        "scenario_text": (
            "Imran missed three days of school for a family function and asks his friend Neeraj to sign his "
            "attendance register. Neeraj is the class attendance captain, and the teacher trusts his "
            "signature.\n\n"
            "Imran says, 'It won't harm anyone, and I can't get below 75%.' Neeraj knows the attendance rule "
            "is strict, but he also knows Imran's family situation is complicated.\n\n"
            "If Neeraj refuses, Imran might be disqualified from practicals. If he agrees, Neeraj risks his "
            "position and feels uneasy about bending the rules."
        ),
        "scenario_text_hi": (
            "Imran एक फ़ैमिली फ़ंक्शन की वजह से तीन दिन स्कूल नहीं आ पाया और अपने दोस्त Neeraj से "
            "कहता है कि उसकी अटेंडेंस रजिस्टर में साइन कर दे। Neeraj क्लास का अटेंडेंस कैप्टन है और "
            "टीचर को उसके साइन पर भरोसा है।\n\n"
            "Imran कहता है, 'इससे किसी का नुकसान नहीं होगा, और मेरा 75% से नीचे नहीं जाना चाहिए।' "
            "Neeraj जानता है कि अटेंडेंस का रूल स्ट्रिक्ट है, लेकिन उसे ये भी पता है कि Imran की "
            "फ़ैमिली सिचुएशन कॉम्प्लिकेटेड है।\n\n"
            "अगर Neeraj मना करता है तो Imran प्रैक्टिकल्स से डिसक्वालिफ़ाई हो सकता है। अगर मान जाता "
            "है तो Neeraj की पोज़ीशन ख़तरे में पड़ सकती है और रूल्स तोड़ने पर उसे बेचैनी होगी।"
        ),
        "probing_angles": [
            "How does Neeraj interpret responsibility when rules clash with compassion?",
            "What are the risks he is willing to take for a friend?",
            "How might he find a solution that doesn't involve falsifying records?",
            "What emotions are strongest for him: guilt, fear, or loyalty?",
        ],
    },
    {
        "id": "SP-03",
        "title": "Birthday Exclusion",
        "category": "Social Pressure",
        "target_class": "8-10",
        "scenario_text": (
            "Sneha is planning her class 9 birthday party and wants to invite everyone. Her close friends "
            "insist she should not invite a classmate, Tara, who they say is 'too dramatic.' They warn her "
            "that inviting Tara will 'ruin the vibe.'\n\n"
            "Sneha feels uncomfortable because Tara has been kind to her in the past, but Sneha also wants "
            "her party to go smoothly. Her friends say, 'It's your birthday, but we are the ones coming.'\n\n"
            "Sneha feels pulled between fairness and keeping her group happy. She worries that if she goes "
            "against them, they might spoil the party or exclude her later."
        ),
        "scenario_text_hi": (
            "Sneha अपनी क्लास 9 की बर्थडे पार्टी प्लान कर रही है और सबको बुलाना चाहती है। उसकी "
            "करीबी फ्रेंड्स ज़ोर दे रही हैं कि वो अपनी क्लासमेट Tara को न बुलाए क्योंकि वो 'बहुत "
            "ड्रामेटिक' है। वो कहती हैं कि Tara को बुलाने से 'वाइब ख़राब होगी।'\n\n"
            "Sneha को अनकम्फ़र्टेबल लग रहा है क्योंकि Tara उसके साथ हमेशा अच्छी रही है, लेकिन Sneha "
            "ये भी चाहती है कि पार्टी अच्छे से हो। उसकी फ्रेंड्स कहती हैं, 'बर्थडे तेरा है, लेकिन "
            "आने तो हम हैं।'\n\n"
            "Sneha फ़ेयरनेस और अपने ग्रुप को खुश रखने के बीच खिंची हुई है। उसे डर है कि अगर उसने "
            "फ्रेंड्स की बात नहीं मानी तो वो पार्टी ख़राब कर देंगी या बाद में उसे अलग कर देंगी।"
        ),
        "probing_angles": [
            "What values matter most to Sneha in this decision?",
            "How does she handle guilt versus social comfort?",
            "What could she say to her friends without escalating conflict?",
            "How might this moment shape her confidence in group settings?",
        ],
    },
    {
        "id": "FC-03",
        "title": "Hostel or Home",
        "category": "Family Conflicts",
        "target_class": "11-12",
        "scenario_text": (
            "Rakesh has a chance to join a hostel-based coaching program for NEET in a nearby city. He wants "
            "to go because the coaching is reputed, and he thinks the environment will help him focus. His "
            "mother is hesitant and says, 'You are too young to live away; stay at home and study.'\n\n"
            "His father is undecided and worries about expenses. Rakesh feels frustrated because he thinks his "
            "parents don't trust him, while his parents feel he doesn't understand family constraints.\n\n"
            "The admission deadline is close. Rakesh is anxious and doesn't know how to convince his family "
            "without making it a fight."
        ),
        "scenario_text_hi": (
            "Rakesh को पास के शहर में एक हॉस्टल-बेस्ड NEET कोचिंग प्रोग्राम में जाने का मौका मिला है। "
            "वो जाना चाहता है क्योंकि कोचिंग की रेपुटेशन अच्छी है और उसे लगता है कि वहाँ का "
            "एनवायरनमेंट फ़ोकस करने में मदद करेगा। उसकी मम्मी हिचकिचा रही हैं और कहती हैं, 'तुम अभी "
            "बाहर रहने के लिए छोटे हो; घर पर रहकर पढ़ो।'\n\n"
            "उसके पापा अनडिसाइडेड हैं और खर्चे की चिंता कर रहे हैं। Rakesh को फ़्रस्ट्रेशन हो रहा है "
            "क्योंकि उसे लगता है कि पैरेंट्स उस पर भरोसा नहीं करते, जबकि उसके पैरेंट्स को लगता है कि "
            "वो फ़ैमिली की मजबूरियाँ नहीं समझता।\n\n"
            "एडमिशन की डेडलाइन करीब है। Rakesh परेशान है और समझ नहीं आ रहा कि फ़ैमिली को कैसे "
            "मनाए बिना लड़ाई किए।"
        ),
        "probing_angles": [
            "How does Rakesh balance independence with family expectations?",
            "What fears might his parents have that he hasn't acknowledged?",
            "What practical compromises could address both sides?",
            "How does the time pressure affect his communication?",
        ],
    },
    {
        "id": "DE-03",
        "title": "Fake Account Screenshot",
        "category": "Digital Ethics",
        "target_class": "11-12",
        "scenario_text": (
            "A fake Instagram account is created to mock a teacher's accent and posts embarrassing screenshots. "
            "Varun in class 12 is added to the group chat where the screenshots are shared, and his classmates "
            "urge him to like and share.\n\n"
            "Varun feels the jokes are disrespectful, but he also worries about being seen as the teacher's "
            "favorite if he objects. He knows the school has strict cyber rules and that such actions could "
            "lead to suspension.\n\n"
            "He considers leaving the group, but his friends say, 'Relax, it is just online.' Varun feels torn "
            "between morality, friendship, and fear of consequences."
        ),
        "scenario_text_hi": (
            "किसी ने एक फ़ेक Instagram अकाउंट बनाया है जिसमें एक टीचर के एक्सेंट का मज़ाक उड़ाया जा "
            "रहा है और शर्मनाक स्क्रीनशॉट्स पोस्ट किए जा रहे हैं। क्लास 12 के Varun को उस ग्रुप चैट "
            "में एड किया गया है जहाँ ये स्क्रीनशॉट्स शेयर हो रहे हैं, और उसके क्लासमेट्स उससे लाइक "
            "और शेयर करने को कह रहे हैं।\n\n"
            "Varun को लगता है कि ये मज़ाक बेइज़्ज़ती है, लेकिन उसे डर भी है कि अगर वो बोला तो लोग उसे "
            "टीचर का चमचा समझेंगे। उसे पता है कि स्कूल के साइबर रूल्स स्ट्रिक्ट हैं और ऐसा करने पर "
            "सस्पेंशन हो सकता है।\n\n"
            "वो ग्रुप छोड़ने के बारे में सोचता है, लेकिन उसके दोस्त कहते हैं, 'रिलैक्स, बस ऑनलाइन "
            "है।' Varun नैतिकता, दोस्ती और नतीजों के डर के बीच फँसा हुआ है।"
        ),
        "probing_angles": [
            "What does respect look like for Varun in a digital space?",
            "How does he handle the fear of standing out in his peer group?",
            "What actions feel safe and aligned with his values?",
            "How might he respond if he were the target?",
        ],
    },
]


def get_case_studies():
    return CASE_STUDIES


def get_case_study_for_class(class_level):
    class_str = str(class_level)
    for study in CASE_STUDIES:
        target = str(study.get("target_class", ""))
        if class_str in target:
            return study
    return CASE_STUDIES[0] if CASE_STUDIES else None


def _row_to_dict(row, in_db: bool = True) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "category": row.category,
        "target_class": row.target_class,
        "scenario_text": row.scenario_text,
        "scenario_text_hi": row.scenario_text_hi or "",
        "probing_angles": row.probing_angles or [],
        "_in_db": in_db,
    }


# IDs of case studies that ship with the app (used to detect built-ins)
_BUILTIN_IDS: frozenset[str] = frozenset(cs["id"] for cs in CASE_STUDIES)


def get_all_case_studies(db=None) -> list[dict]:
    """Return built-in case studies merged with any custom ones saved to the DB.

    DB rows take precedence over static entries with the same ID — this lets
    counsellors override a built-in by editing it (the DB copy shadows the static one).
    """
    # Start from static list, preserving order
    result: dict[str, dict] = {
        cs["id"]: dict(cs) | {"_in_db": False} for cs in CASE_STUDIES
    }
    if db is None:
        return list(result.values())
    try:
        from counselai.storage.models import CaseStudy as CaseStudyRow
        rows = db.query(CaseStudyRow).order_by(CaseStudyRow.created_at).all()
        for row in rows:
            result[row.id] = _row_to_dict(row, in_db=True)
    except Exception:
        pass
    return list(result.values())


def get_case_study_by_id(cs_id: str, db=None) -> dict | None:
    """Return a single case study by ID. DB entry takes priority over static."""
    if db is not None:
        try:
            from counselai.storage.models import CaseStudy as CaseStudyRow
            row = db.query(CaseStudyRow).filter(CaseStudyRow.id == cs_id).first()
            if row is not None:
                return _row_to_dict(row, in_db=True)
        except Exception:
            pass
    for cs in CASE_STUDIES:
        if cs.get("id") == cs_id:
            return dict(cs) | {"_in_db": False}
    return None


def is_builtin(cs_id: str) -> bool:
    """Return True if this ID belongs to a shipped built-in case study."""
    return cs_id in _BUILTIN_IDS


def generate_case_study_id(category: str, db=None) -> str:
    """Auto-generate the next sequential ID for a given category (e.g. 'ED-05')."""
    prefix = CATEGORY_PREFIXES.get(category, "CS")
    all_cs = get_all_case_studies(db)
    existing = [
        cs["id"] for cs in all_cs
        if cs["id"].startswith(prefix + "-") and cs["id"][len(prefix) + 1:].isdigit()
    ]
    max_num = 0
    for cs_id in existing:
        try:
            max_num = max(max_num, int(cs_id[len(prefix) + 1:]))
        except ValueError:
            pass
    return f"{prefix}-{max_num + 1:02d}"
