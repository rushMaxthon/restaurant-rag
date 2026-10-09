import type { Translations } from '../types';

/**
 * Profile, sign-in, permissions, the intro cards, the spotlight guide, the
 * tab bar and the app chrome (connection banner, crash screen).
 */
const en = {
  // Tab bar
  'account.tab.home': 'Home',
  'account.tab.orders': 'Orders',
  'account.tab.earnings': 'Earnings',
  'account.tab.history': 'History',
  'account.tab.profile': 'Profile',

  // Profile
  'account.profile.title': 'Profile',
  'account.profile.vehicleBike': 'Motorbike',
  'account.profile.vehicleScooter': 'Scooter',
  'account.profile.vehicleCycle': 'Bicycle',
  'account.profile.finishFirstTitle': 'Finish your delivery first',
  'account.profile.finishFirstBody':
    'You cannot sign out while carrying an order.',
  'account.profile.signOutTitle': 'Sign out?',
  'account.profile.signOutBody': 'You will stop getting orders on this phone.',
  'account.profile.stay': 'Stay',
  'account.profile.signOut': 'Sign out',
  'account.profile.settings': 'SETTINGS',
  'account.profile.permissions': 'Permissions',
  'account.profile.appearance': 'Appearance',
  'account.profile.dark': 'Dark',
  'account.profile.light': 'Light',
  'account.profile.modeFromPhone': '{mode} · phone',
  'account.profile.highContrast': 'High contrast',
  'account.profile.highContrastHint': 'For bright sun',
  'account.profile.guide': 'GUIDE',
  'account.profile.howItWorks': 'How the app works',
  'account.profile.showTips': 'Show tips again',
  'account.profile.testAlert': 'Test the order alert',
  'account.profile.listen': 'Listen…',
  'account.profile.notificationsOff': 'Notifications are off',
  'account.profile.help': 'HELP',
  'account.profile.callSupport': 'Call support',

  // Appearance choices (theme/preference.ts); Light/Dark labels are the profile.* ones
  'account.theme.systemLabel': 'Follow the phone',
  'account.theme.systemHint': 'Dark at night if your phone is',
  'account.theme.lightHint': 'Easier in bright sun',
  'account.theme.darkHint': 'Easier on the eyes at night',

  // Sign in
  'account.login.phoneProblem': 'Enter your 10-digit mobile number',
  'account.login.passwordProblem': 'Your password has at least 8 characters',
  'account.login.mismatch': 'That phone number and password do not match.',
  'account.login.failed': 'Could not sign in. Try again.',
  'account.login.welcome': 'Welcome back',
  'account.login.lead': 'Sign in to start taking orders.',
  'account.login.mobile': 'Mobile number',
  'account.login.password': 'Password',
  'account.login.passwordPlaceholder': 'Your password',
  'account.login.signIn': 'Sign in',
  'account.login.help': 'Forgot your password?',
  'account.login.callManager': 'Call your manager',
  'account.splash.tagline': 'Deliver smiles, earn more.',

  // Permissions
  'account.perm.title': 'Three quick things',
  'account.perm.lead': 'The app needs these to send you orders.',
  'account.perm.location': 'Location',
  'account.perm.locationWhy':
    'We send you orders from restaurants near you, and customers see you arriving.',
  'account.perm.notifications': 'Notifications',
  'account.perm.notificationsWhy':
    'A new order rings even when your screen is off, so you never miss one.',
  'account.perm.battery': 'Run in the background',
  'account.perm.batteryWhy':
    'Without this, your phone closes the app to save battery and orders stop reaching you.',
  'account.perm.allow': 'Allow',
  'account.perm.autoStartTitle': 'Phone has its own battery saver?',
  'account.perm.autoStartBody':
    'Xiaomi, Realme, Oppo and Vivo add one more switch. Turn on auto-start for this app.',
  'account.perm.open': 'Open',
  'account.perm.allSet': 'All set',
  'account.perm.notNow': 'Not now',
  'account.perm.reasonLocation': 'Allow location to start getting orders',
  'account.perm.reasonNotifications':
    'Allow notifications to start getting orders',
  'account.perm.reasonBattery':
    'Let the app run in the background to start getting orders',

  // Intro cards
  'account.intro.howItWorks': 'HOW IT WORKS',
  'account.intro.letsSetUp': "Let's set up",
  'account.intro.cardOf': 'Card {n} of {count}',
  'account.intro.slideLabel': 'Arrived at restaurant',
  'account.intro.slideDone': "That's it. The customer now sees you're there.",
  'account.intro.slideTry': 'Try it: slide the knob all the way.',
  'account.intro.youEarned': 'YOU EARNED',
  'account.intro.onlineTitle': 'Go online when you start',
  'account.intro.onlineBody':
    'Orders only come while this is on. Switch it off when your shift ends. Try it.',
  'account.intro.ringTitle': 'An order rings like a call',
  'account.intro.ringBody':
    'You see what it pays and how far it is. Accept before the ring runs out - declining costs nothing.',
  'account.intro.slideTitle': 'Slide at every stop',
  'account.intro.slideBody':
    'Reached the restaurant? Slide. Picked up? Slide. A slide, not a tap, so a bump on the road cannot do it for you.',
  'account.intro.codeTitle': "The customer's code pays you",
  'account.intro.codeBody':
    'At the door, ask for the 4-digit code on their order page. Type it and the delivery is done - and paid.',

  // Spotlight tips (guide/tours.ts)
  'account.guide.stepOf': '{n} OF {count}',
  'account.tip.homeToggleTitle': 'Go online to get orders',
  'account.tip.homeToggleBody':
    "Tap here at the start of your shift. Orders only come while you're online.",
  'account.tip.homeTodayTitle': "What you've made today",
  'account.tip.homeTodayBody':
    'Updates after every delivery. The Earnings tab has the whole week.',
  'account.tip.tabOrdersTitle': 'Orders waiting near you',
  'account.tip.tabOrdersBody':
    "Any order nobody has taken yet. Take one from here when you're online and free.",
  'account.tip.ordersTakeTitle': 'Take an order',
  'account.tip.ordersTakeBody':
    'Looking is free. Taking needs you online with no delivery in hand.',
  'account.tip.tripStepsTitle': 'Where you are',
  'account.tip.tripStepsBody':
    'Four steps: restaurant, collect, customer, deliver. The bar fills as you go.',
  'account.tip.tripSlideTitle': "Slide when you're there",
  'account.tip.tripSlideBody':
    "Only slide once you've actually arrived. It tells the customer where their food is.",
  'account.tip.tripOtpTitle': 'Ask for the code',
  'account.tip.tripOtpBody':
    "The customer has a 4-digit code on their order page. Type it and you're paid.",
  'account.tip.earningsUnpaidTitle': 'To be paid',
  'account.tip.earningsUnpaidBody':
    "Everything you've earned that hasn't reached your bank yet. Payments appear below.",

  // App chrome
  'account.offline': 'No connection. We keep trying.',
  'account.crash.title': 'Something went wrong',
  'account.crash.body':
    'Your delivery and status are safe on the server. Tap below to reload.',
  'account.language.title': 'Language',
  'account.language.phone': 'Follow the phone',
  'account.language.phoneHint': 'Now {name}',
} as const;

const hi: Translations<typeof en> = {
  'account.tab.home': 'होम',
  'account.tab.orders': 'ऑर्डर',
  'account.tab.earnings': 'कमाई',
  'account.tab.history': 'हिस्ट्री',
  'account.tab.profile': 'प्रोफाइल',

  'account.profile.title': 'प्रोफाइल',
  'account.profile.vehicleBike': 'मोटरसाइकिल',
  'account.profile.vehicleScooter': 'स्कूटर',
  'account.profile.vehicleCycle': 'साइकिल',
  'account.profile.finishFirstTitle': 'पहले डिलीवरी पूरी करें',
  'account.profile.finishFirstBody':
    'ऑर्डर साथ में हो तब आप साइन आउट नहीं कर सकते।',
  'account.profile.signOutTitle': 'साइन आउट करें?',
  'account.profile.signOutBody': 'इस फोन पर ऑर्डर आना बंद हो जाएंगे।',
  'account.profile.stay': 'रहने दें',
  'account.profile.signOut': 'साइन आउट',
  'account.profile.settings': 'सेटिंग्स',
  'account.profile.permissions': 'परमिशन',
  'account.profile.appearance': 'थीम',
  'account.profile.dark': 'डार्क',
  'account.profile.light': 'लाइट',
  'account.profile.modeFromPhone': '{mode} · फोन',
  'account.profile.highContrast': 'हाई कॉन्ट्रास्ट',
  'account.profile.highContrastHint': 'तेज़ धूप के लिए',
  'account.profile.guide': 'गाइड',
  'account.profile.howItWorks': 'ऐप कैसे चलता है',
  'account.profile.showTips': 'टिप्स फिर दिखाएं',
  'account.profile.testAlert': 'ऑर्डर अलर्ट टेस्ट करें',
  'account.profile.listen': 'सुनिए…',
  'account.profile.notificationsOff': 'नोटिफिकेशन बंद हैं',
  'account.profile.help': 'मदद',
  'account.profile.callSupport': 'सपोर्ट को कॉल करें',

  'account.theme.systemLabel': 'फोन जैसा',
  'account.theme.systemHint': 'फोन रात में डार्क हो तो यह भी',
  'account.theme.lightHint': 'तेज़ धूप में साफ़ दिखे',
  'account.theme.darkHint': 'रात में आंखों को आराम',

  'account.login.phoneProblem': 'अपना 10 अंकों का मोबाइल नंबर डालें',
  'account.login.passwordProblem': 'पासवर्ड कम से कम 8 अक्षर का होता है',
  'account.login.mismatch': 'फोन नंबर और पासवर्ड मेल नहीं खाते।',
  'account.login.failed': 'साइन इन नहीं हो पाया। फिर से कोशिश करें।',
  'account.login.welcome': 'फिर से स्वागत है',
  'account.login.lead': 'ऑर्डर लेना शुरू करने के लिए साइन इन करें।',
  'account.login.mobile': 'मोबाइल नंबर',
  'account.login.password': 'पासवर्ड',
  'account.login.passwordPlaceholder': 'आपका पासवर्ड',
  'account.login.signIn': 'साइन इन',
  'account.login.help': 'पासवर्ड भूल गए?',
  'account.login.callManager': 'मैनेजर को कॉल करें',
  'account.splash.tagline': 'खुशियां पहुंचाएं, ज़्यादा कमाएं।',

  'account.perm.title': 'बस तीन चीज़ें',
  'account.perm.lead': 'आपको ऑर्डर भेजने के लिए ऐप को इनकी ज़रूरत है।',
  'account.perm.location': 'लोकेशन',
  'account.perm.locationWhy':
    'हम आपको पास के रेस्टोरेंट से ऑर्डर भेजते हैं, और ग्राहक देख पाते हैं कि आप आ रहे हैं।',
  'account.perm.notifications': 'नोटिफिकेशन',
  'account.perm.notificationsWhy':
    'स्क्रीन बंद हो तब भी नया ऑर्डर बजेगा, ताकि कोई ऑर्डर न छूटे।',
  'account.perm.battery': 'बैकग्राउंड में चलने दें',
  'account.perm.batteryWhy':
    'इसके बिना फोन बैटरी बचाने के लिए ऐप बंद कर देता है और ऑर्डर आना रुक जाते हैं।',
  'account.perm.allow': 'अनुमति दें',
  'account.perm.autoStartTitle': 'फोन में अलग बैटरी सेवर है?',
  'account.perm.autoStartBody':
    'Xiaomi, Realme, Oppo और Vivo में एक और स्विच होता है। इस ऐप के लिए ऑटो-स्टार्ट चालू करें।',
  'account.perm.open': 'खोलें',
  'account.perm.allSet': 'सब तैयार',
  'account.perm.notNow': 'अभी नहीं',
  'account.perm.reasonLocation': 'ऑर्डर पाने के लिए लोकेशन चालू करें',
  'account.perm.reasonNotifications': 'ऑर्डर पाने के लिए नोटिफिकेशन चालू करें',
  'account.perm.reasonBattery':
    'ऑर्डर पाने के लिए ऐप को बैकग्राउंड में चलने दें',

  'account.intro.howItWorks': 'ऐप कैसे चलता है',
  'account.intro.letsSetUp': 'सेटअप करें',
  'account.intro.cardOf': '{count} में से कार्ड {n}',
  'account.intro.slideLabel': 'रेस्टोरेंट पहुंच गए',
  'account.intro.slideDone': 'बस इतना ही। अब ग्राहक को पता है कि आप पहुंच गए।',
  'account.intro.slideTry': 'करके देखें: बटन को पूरा स्लाइड करें।',
  'account.intro.youEarned': 'आपकी कमाई',
  'account.intro.onlineTitle': 'काम शुरू करते ही ऑनलाइन जाएं',
  'account.intro.onlineBody':
    'यह चालू हो तभी ऑर्डर आते हैं। शिफ्ट खत्म हो तो बंद करें। करके देखें।',
  'account.intro.ringTitle': 'ऑर्डर कॉल की तरह बजता है',
  'account.intro.ringBody':
    'दिखता है कितना मिलेगा और कितनी दूर है। रिंग खत्म होने से पहले स्वीकार करें - मना करने पर कुछ नहीं कटता।',
  'account.intro.slideTitle': 'हर स्टॉप पर स्लाइड करें',
  'account.intro.slideBody':
    'रेस्टोरेंट पहुंचे? स्लाइड करें। पिकअप किया? स्लाइड करें। टैप नहीं, स्लाइड - ताकि सड़क के झटके से अपने आप न हो जाए।',
  'account.intro.codeTitle': 'ग्राहक के कोड से पैसे मिलते हैं',
  'account.intro.codeBody':
    'दरवाज़े पर ग्राहक से उनके ऑर्डर पेज का 4 अंकों का कोड मांगें। कोड डालते ही डिलीवरी पूरी - और पैसे पक्के।',

  'account.guide.stepOf': '{count} में से {n}',
  'account.tip.homeToggleTitle': 'ऑर्डर के लिए ऑनलाइन जाएं',
  'account.tip.homeToggleBody':
    'शिफ्ट शुरू होते ही यहां टैप करें। ऑनलाइन रहने पर ही ऑर्डर आते हैं।',
  'account.tip.homeTodayTitle': 'आज की कमाई',
  'account.tip.homeTodayBody':
    'हर डिलीवरी के बाद अपडेट होती है। पूरे हफ्ते की कमाई, कमाई टैब में।',
  'account.tip.tabOrdersTitle': 'आपके पास इंतज़ार में ऑर्डर',
  'account.tip.tabOrdersBody':
    'जो ऑर्डर अभी किसी ने नहीं लिया। ऑनलाइन और फ्री हों तो यहां से ऑर्डर लें।',
  'account.tip.ordersTakeTitle': 'ऑर्डर लें',
  'account.tip.ordersTakeBody':
    'देखना हमेशा खुला है। लेने के लिए ऑनलाइन रहें और हाथ में कोई डिलीवरी न हो।',
  'account.tip.tripStepsTitle': 'आप कहां तक पहुंचे',
  'account.tip.tripStepsBody':
    'चार स्टेप: रेस्टोरेंट, पिकअप, ग्राहक, डिलीवरी। आगे बढ़ते ही बार भरता है।',
  'account.tip.tripSlideTitle': 'पहुंचकर स्लाइड करें',
  'account.tip.tripSlideBody':
    'सच में पहुंचने के बाद ही स्लाइड करें। इससे ग्राहक को पता चलता है कि खाना कहां है।',
  'account.tip.tripOtpTitle': 'कोड मांगें',
  'account.tip.tripOtpBody':
    'ग्राहक के ऑर्डर पेज पर 4 अंकों का कोड है। उसे डालें और पैसे पक्के।',
  'account.tip.earningsUnpaidTitle': 'मिलना बाकी',
  'account.tip.earningsUnpaidBody':
    'आपकी वो कमाई जो अभी बैंक में नहीं आई। पेमेंट नीचे दिखते हैं।',

  'account.offline': 'इंटरनेट नहीं है। हम कोशिश कर रहे हैं।',
  'account.crash.title': 'कुछ गड़बड़ हो गई',
  'account.crash.body':
    'आपकी डिलीवरी और स्टेटस सर्वर पर सुरक्षित हैं। दोबारा लोड करने के लिए नीचे टैप करें।',
  'account.language.title': 'भाषा',
  'account.language.phone': 'फोन जैसी',
  'account.language.phoneHint': 'अभी {name}',
};

const gu: Translations<typeof en> = {
  'account.tab.home': 'હોમ',
  'account.tab.orders': 'ઓર્ડર',
  'account.tab.earnings': 'કમાણી',
  'account.tab.history': 'હિસ્ટ્રી',
  'account.tab.profile': 'પ્રોફાઇલ',

  'account.profile.title': 'પ્રોફાઇલ',
  'account.profile.vehicleBike': 'મોટરસાઇકલ',
  'account.profile.vehicleScooter': 'સ્કૂટર',
  'account.profile.vehicleCycle': 'સાઇકલ',
  'account.profile.finishFirstTitle': 'પહેલા ડિલિવરી પૂરી કરો',
  'account.profile.finishFirstBody':
    'ઓર્ડર સાથે હોય ત્યારે તમે સાઇન આઉટ નહીં કરી શકો.',
  'account.profile.signOutTitle': 'સાઇન આઉટ કરવું છે?',
  'account.profile.signOutBody': 'આ ફોન પર ઓર્ડર આવવાનું બંધ થઈ જશે.',
  'account.profile.stay': 'રહેવા દો',
  'account.profile.signOut': 'સાઇન આઉટ',
  'account.profile.settings': 'સેટિંગ્સ',
  'account.profile.permissions': 'પરમિશન',
  'account.profile.appearance': 'થીમ',
  'account.profile.dark': 'ડાર્ક',
  'account.profile.light': 'લાઇટ',
  'account.profile.modeFromPhone': '{mode} · ફોન',
  'account.profile.highContrast': 'હાઇ કૉન્ટ્રાસ્ટ',
  'account.profile.highContrastHint': 'તેજ તડકા માટે',
  'account.profile.guide': 'ગાઇડ',
  'account.profile.howItWorks': 'એપ કેવી રીતે ચાલે છે',
  'account.profile.showTips': 'ટિપ્સ ફરી બતાવો',
  'account.profile.testAlert': 'ઓર્ડર અલર્ટ ટેસ્ટ કરો',
  'account.profile.listen': 'સાંભળો…',
  'account.profile.notificationsOff': 'નોટિફિકેશન બંધ છે',
  'account.profile.help': 'મદદ',
  'account.profile.callSupport': 'સપોર્ટને કૉલ કરો',

  'account.theme.systemLabel': 'ફોન મુજબ',
  'account.theme.systemHint': 'ફોન રાત્રે ડાર્ક હોય તો આ પણ',
  'account.theme.lightHint': 'તડકામાં સાફ દેખાય',
  'account.theme.darkHint': 'રાત્રે આંખોને આરામ',

  'account.login.phoneProblem': 'તમારો 10 આંકડાનો મોબાઇલ નંબર નાખો',
  'account.login.passwordProblem': 'પાસવર્ડ ઓછામાં ઓછા 8 અક્ષરનો હોય છે',
  'account.login.mismatch': 'ફોન નંબર અને પાસવર્ડ મેળ ખાતા નથી.',
  'account.login.failed': 'સાઇન ઇન ન થયું. ફરી પ્રયાસ કરો.',
  'account.login.welcome': 'ફરી સ્વાગત છે',
  'account.login.lead': 'ઓર્ડર લેવાનું શરૂ કરવા સાઇન ઇન કરો.',
  'account.login.mobile': 'મોબાઇલ નંબર',
  'account.login.password': 'પાસવર્ડ',
  'account.login.passwordPlaceholder': 'તમારો પાસવર્ડ',
  'account.login.signIn': 'સાઇન ઇન',
  'account.login.help': 'પાસવર્ડ ભૂલી ગયા?',
  'account.login.callManager': 'મેનેજરને કૉલ કરો',
  'account.splash.tagline': 'ખુશી પહોંચાડો, વધુ કમાઓ.',

  'account.perm.title': 'બસ ત્રણ વસ્તુ',
  'account.perm.lead': 'તમને ઓર્ડર મોકલવા એપને આની જરૂર છે.',
  'account.perm.location': 'લોકેશન',
  'account.perm.locationWhy':
    'અમે તમને નજીકના રેસ્ટોરન્ટના ઓર્ડર મોકલીએ છીએ, અને ગ્રાહક જોઈ શકે છે કે તમે આવી રહ્યા છો.',
  'account.perm.notifications': 'નોટિફિકેશન',
  'account.perm.notificationsWhy':
    'સ્ક્રીન બંધ હોય ત્યારે પણ નવો ઓર્ડર વાગશે, જેથી એક પણ ઓર્ડર ન છૂટે.',
  'account.perm.battery': 'બેકગ્રાઉન્ડમાં ચાલવા દો',
  'account.perm.batteryWhy':
    'આના વગર ફોન બેટરી બચાવવા એપ બંધ કરી દે છે અને ઓર્ડર આવતા બંધ થઈ જાય છે.',
  'account.perm.allow': 'મંજૂરી આપો',
  'account.perm.autoStartTitle': 'ફોનમાં અલગ બેટરી સેવર છે?',
  'account.perm.autoStartBody':
    'Xiaomi, Realme, Oppo અને Vivo માં એક વધુ સ્વિચ હોય છે. આ એપ માટે ઑટો-સ્ટાર્ટ ચાલુ કરો.',
  'account.perm.open': 'ખોલો',
  'account.perm.allSet': 'બધું તૈયાર',
  'account.perm.notNow': 'હમણાં નહીં',
  'account.perm.reasonLocation': 'ઓર્ડર મેળવવા લોકેશન ચાલુ કરો',
  'account.perm.reasonNotifications': 'ઓર્ડર મેળવવા નોટિફિકેશન ચાલુ કરો',
  'account.perm.reasonBattery': 'ઓર્ડર મેળવવા એપને બેકગ્રાઉન્ડમાં ચાલવા દો',

  'account.intro.howItWorks': 'એપ કેવી રીતે ચાલે છે',
  'account.intro.letsSetUp': 'સેટઅપ કરો',
  'account.intro.cardOf': '{count} માંથી કાર્ડ {n}',
  'account.intro.slideLabel': 'રેસ્ટોરન્ટ પહોંચ્યા',
  'account.intro.slideDone':
    'બસ આટલું જ. હવે ગ્રાહકને ખબર છે કે તમે પહોંચી ગયા.',
  'account.intro.slideTry': 'કરી જુઓ: બટનને છેક સુધી સ્લાઇડ કરો.',
  'account.intro.youEarned': 'તમારી કમાણી',
  'account.intro.onlineTitle': 'કામ શરૂ કરો ત્યારે ઓનલાઇન થાઓ',
  'account.intro.onlineBody':
    'આ ચાલુ હોય ત્યારે જ ઓર્ડર આવે છે. શિફ્ટ પૂરી થાય ત્યારે બંધ કરો. કરી જુઓ.',
  'account.intro.ringTitle': 'ઓર્ડર કૉલની જેમ વાગે છે',
  'account.intro.ringBody':
    'દેખાય છે કે કેટલા મળશે અને કેટલું દૂર છે. રિંગ પૂરી થાય એ પહેલાં સ્વીકારો - ના પાડવાથી કંઈ કપાતું નથી.',
  'account.intro.slideTitle': 'દરેક સ્ટોપ પર સ્લાઇડ કરો',
  'account.intro.slideBody':
    'રેસ્ટોરન્ટ પહોંચ્યા? સ્લાઇડ કરો. પિકઅપ કર્યું? સ્લાઇડ કરો. ટૅપ નહીં, સ્લાઇડ - જેથી રસ્તાના ઝટકાથી જાતે ન થઈ જાય.',
  'account.intro.codeTitle': 'ગ્રાહકના કોડથી પૈસા મળે છે',
  'account.intro.codeBody':
    'દરવાજે ગ્રાહક પાસે તેમના ઓર્ડર પેજનો 4 આંકડાનો કોડ માંગો. કોડ નાખતાં જ ડિલિવરી પૂરી - અને પૈસા પાકા.',

  'account.guide.stepOf': '{count} માંથી {n}',
  'account.tip.homeToggleTitle': 'ઓર્ડર માટે ઓનલાઇન થાઓ',
  'account.tip.homeToggleBody':
    'શિફ્ટ શરૂ થાય ત્યારે અહીં ટૅપ કરો. ઓનલાઇન હો ત્યારે જ ઓર્ડર આવે છે.',
  'account.tip.homeTodayTitle': 'આજની કમાણી',
  'account.tip.homeTodayBody':
    'દરેક ડિલિવરી પછી અપડેટ થાય છે. આખા અઠવાડિયાની કમાણી, કમાણી ટૅબમાં.',
  'account.tip.tabOrdersTitle': 'તમારી નજીક રાહ જોતા ઓર્ડર',
  'account.tip.tabOrdersBody':
    'જે ઓર્ડર હજુ કોઈએ નથી લીધો. ઓનલાઇન અને ફ્રી હો ત્યારે અહીંથી ઓર્ડર લો.',
  'account.tip.ordersTakeTitle': 'ઓર્ડર લો',
  'account.tip.ordersTakeBody':
    'જોવાનું હંમેશાં ખુલ્લું છે. લેવા માટે ઓનલાઇન રહો અને હાથમાં કોઈ ડિલિવરી ન હોય.',
  'account.tip.tripStepsTitle': 'તમે ક્યાં સુધી પહોંચ્યા',
  'account.tip.tripStepsBody':
    'ચાર સ્ટેપ: રેસ્ટોરન્ટ, પિકઅપ, ગ્રાહક, ડિલિવરી. આગળ વધો તેમ બાર ભરાય છે.',
  'account.tip.tripSlideTitle': 'પહોંચીને સ્લાઇડ કરો',
  'account.tip.tripSlideBody':
    'ખરેખર પહોંચો પછી જ સ્લાઇડ કરો. એનાથી ગ્રાહકને ખબર પડે છે કે જમવાનું ક્યાં છે.',
  'account.tip.tripOtpTitle': 'કોડ માંગો',
  'account.tip.tripOtpBody':
    'ગ્રાહકના ઓર્ડર પેજ પર 4 આંકડાનો કોડ છે. એ નાખો અને પૈસા પાકા.',
  'account.tip.earningsUnpaidTitle': 'મળવાનું બાકી',
  'account.tip.earningsUnpaidBody':
    'તમારી એ કમાણી જે હજુ બેંકમાં નથી આવી. પેમેન્ટ નીચે દેખાય છે.',

  'account.offline': 'ઇન્ટરનેટ નથી. અમે પ્રયાસ ચાલુ રાખીએ છીએ.',
  'account.crash.title': 'કંઈક ગડબડ થઈ',
  'account.crash.body':
    'તમારી ડિલિવરી અને સ્ટેટસ સર્વર પર સુરક્ષિત છે. ફરી લોડ કરવા નીચે ટૅપ કરો.',
  'account.language.title': 'ભાષા',
  'account.language.phone': 'ફોન મુજબ',
  'account.language.phoneHint': 'હમણાં {name}',
};

export default { en, hi, gu };
