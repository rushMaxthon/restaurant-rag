import type { Translations } from '../types';

/**
 * Words the app writes itself outside any screen: notifications, the shift
 * service, and the fallback error sentences. Server-written messages are
 * never translated here - they arrive as they are.
 */
const en = {
  // Notification channels (Android settings) and the alerts on them
  'system.channelOffers': 'New orders',
  'system.channelOffersDesc':
    'Rings when an order is offered to you. Keep this on while you are online.',
  'system.channelUpdates': 'Trip updates',
  'system.channelUpdatesDesc': 'A delivery you are on was changed or cancelled.',
  'system.offerTitle': 'New delivery order',
  'system.offerBody': 'Tap to see what it pays and accept it.',
  'system.testTitle': 'This is what a new order sounds like',
  'system.testBody': 'A real one shows what it pays and how far it is.',
  'system.cancelledTitle': 'Delivery cancelled',
  'system.cancelledBody':
    'The order was cancelled. Tap to see your earnings for it.',
  // The foreground shift service
  'system.channelShift': 'On shift',
  'system.channelShiftDesc':
    'Shown while you are online, so the app can keep sharing your location.',
  'system.shiftOnlineTitle': 'You are online',
  'system.shiftOnlineBody': 'Looking for orders near you. Tap to open.',
  'system.shiftTripTitle': 'Delivery in progress',
  'system.shiftTripBody':
    'Sharing your location with the customer. Tap to open.',
  // Backend codes, in words for the rider
  'system.errOfferTaken': 'Another rider took this order.',
  'system.errOfferExpired': 'This offer has expired.',
  'system.errOutOfOrder': 'Finish the previous step first.',
  'system.errOtpLocked':
    'Too many wrong codes. Call support to finish this delivery.',
  'system.errTooEarly':
    'Wait a little longer at the door and call the customer twice first.',
  'system.errOnTrip': 'Finish your current delivery before going offline.',
  'system.errTripEnded': 'This delivery has already ended.',
  'system.errValidation': 'Please check what you entered.',
  'system.errAuth': 'Your session has ended. Please sign in again.',
  'system.errForbidden': 'This account cannot use the rider app.',
  'system.errRateLimited': 'Too many tries. Wait a minute and try again.',
  'system.errServer': 'Something went wrong on our side. Try again in a moment.',
  'system.errGeneric': 'Something went wrong. Try again.',
  'system.errNetwork': 'No connection. Check your internet and try again.',
  'system.signedOut': 'You were signed out. Please sign in again.',
  'system.locationUnavailable': 'Location is not available',
  // Taking an order from the board
  'system.claimTaken': 'Another rider took this one first.',
  'system.claimOffline': 'Go online to take orders.',
  'system.claimBusy': 'Finish your current delivery first.',
  'system.claimFailed': 'Could not take this order. Try again.',
  'system.lastMinute': 'Last minute',
  'system.minutesLeft': '{n} min left',
  'system.blockedBusy': 'Finish your current delivery first',
  'system.blockedOffline': 'Go online to take orders',
  'system.takingAnother': 'Taking another order',
  // Going on and off shift
  'system.statusFailed': 'Could not change your status.',
  'system.finishToGoOffline': 'Finish your delivery to go offline',
} as const;

const hi: Translations<typeof en> = {
  'system.channelOffers': 'नए ऑर्डर',
  'system.channelOffersDesc':
    'जब आपको ऑर्डर मिले तब घंटी बजती है। ऑनलाइन रहते समय इसे चालू रखें।',
  'system.channelUpdates': 'ट्रिप अपडेट',
  'system.channelUpdatesDesc': 'आपकी चल रही डिलीवरी बदली गई या कैंसल हुई।',
  'system.offerTitle': 'नया डिलीवरी ऑर्डर',
  'system.offerBody': 'कितना मिलेगा देखने और स्वीकार करने के लिए टैप करें।',
  'system.testTitle': 'नया ऑर्डर ऐसे बजता है',
  'system.testBody': 'असली ऑर्डर में दिखेगा कितना मिलेगा और कितनी दूर है।',
  'system.cancelledTitle': 'डिलीवरी कैंसल',
  'system.cancelledBody': 'ऑर्डर कैंसल हो गया। इसकी कमाई देखने के लिए टैप करें।',
  'system.channelShift': 'शिफ्ट पर',
  'system.channelShiftDesc':
    'ऑनलाइन रहते समय दिखता है, ताकि ऐप आपकी लोकेशन भेजता रहे।',
  'system.shiftOnlineTitle': 'आप ऑनलाइन हैं',
  'system.shiftOnlineBody':
    'आपके पास के ऑर्डर ढूंढ रहे हैं। खोलने के लिए टैप करें।',
  'system.shiftTripTitle': 'डिलीवरी चल रही है',
  'system.shiftTripBody':
    'ग्राहक को आपकी लोकेशन दिख रही है। खोलने के लिए टैप करें।',
  'system.errOfferTaken': 'यह ऑर्डर किसी और राइडर ने ले लिया।',
  'system.errOfferExpired': 'यह ऑफर खत्म हो गया।',
  'system.errOutOfOrder': 'पहले पिछला स्टेप पूरा करें।',
  'system.errOtpLocked':
    'बहुत बार गलत कोड डाला। डिलीवरी पूरी करने के लिए सपोर्ट को कॉल करें।',
  'system.errTooEarly':
    'दरवाज़े पर थोड़ा और रुकें और पहले ग्राहक को दो बार कॉल करें।',
  'system.errOnTrip': 'ऑफलाइन जाने से पहले अभी की डिलीवरी पूरी करें।',
  'system.errTripEnded': 'यह डिलीवरी पहले ही खत्म हो चुकी है।',
  'system.errValidation': 'आपने जो डाला है उसे एक बार चेक करें।',
  'system.errAuth': 'आपका सेशन खत्म हो गया। फिर से साइन इन करें।',
  'system.errForbidden': 'यह अकाउंट राइडर ऐप नहीं चला सकता।',
  'system.errRateLimited': 'बहुत ज़्यादा कोशिश हुई। एक मिनट रुककर फिर से करें।',
  'system.errServer': 'हमारी तरफ से कुछ गड़बड़ हुई। थोड़ी देर में फिर से करें।',
  'system.errGeneric': 'कुछ गड़बड़ हुई। फिर से करें।',
  'system.errNetwork': 'इंटरनेट नहीं है। कनेक्शन चेक करके फिर से करें।',
  'system.signedOut': 'आप साइन आउट हो गए। फिर से साइन इन करें।',
  'system.locationUnavailable': 'लोकेशन नहीं मिल रही',
  'system.claimTaken': 'यह ऑर्डर किसी और राइडर ने पहले ले लिया।',
  'system.claimOffline': 'ऑर्डर लेने के लिए ऑनलाइन जाएं।',
  'system.claimBusy': 'पहले अभी की डिलीवरी पूरी करें।',
  'system.claimFailed': 'यह ऑर्डर नहीं ले पाए। फिर से करें।',
  'system.lastMinute': 'आखिरी मिनट',
  'system.minutesLeft': '{n} मिनट बाकी',
  'system.blockedBusy': 'पहले अभी की डिलीवरी पूरी करें',
  'system.blockedOffline': 'ऑर्डर लेने के लिए ऑनलाइन जाएं',
  'system.takingAnother': 'दूसरा ऑर्डर ले रहे हैं',
  'system.statusFailed': 'आपका स्टेटस नहीं बदल पाए।',
  'system.finishToGoOffline': 'ऑफलाइन जाने के लिए डिलीवरी पूरी करें',
};

const gu: Translations<typeof en> = {
  'system.channelOffers': 'નવા ઓર્ડર',
  'system.channelOffersDesc':
    'તમને ઓર્ડર મળે ત્યારે રિંગ વાગે છે. ઓનલાઇન હો ત્યારે આ ચાલુ રાખો.',
  'system.channelUpdates': 'ટ્રિપ અપડેટ',
  'system.channelUpdatesDesc': 'તમારી ચાલુ ડિલિવરી બદલાઈ કે કેન્સલ થઈ.',
  'system.offerTitle': 'નવો ડિલિવરી ઓર્ડર',
  'system.offerBody': 'કેટલા મળશે તે જોવા અને સ્વીકારવા ટેપ કરો.',
  'system.testTitle': 'નવો ઓર્ડર આવો વાગે છે',
  'system.testBody': 'સાચા ઓર્ડરમાં દેખાશે કેટલા મળશે અને કેટલું દૂર છે.',
  'system.cancelledTitle': 'ડિલિવરી કેન્સલ',
  'system.cancelledBody': 'ઓર્ડર કેન્સલ થયો. તેની કમાણી જોવા ટેપ કરો.',
  'system.channelShift': 'શિફ્ટ પર',
  'system.channelShiftDesc':
    'ઓનલાઇન હો ત્યારે દેખાય છે, જેથી એપ તમારું લોકેશન મોકલતી રહે.',
  'system.shiftOnlineTitle': 'તમે ઓનલાઇન છો',
  'system.shiftOnlineBody': 'તમારી નજીકના ઓર્ડર શોધીએ છીએ. ખોલવા ટેપ કરો.',
  'system.shiftTripTitle': 'ડિલિવરી ચાલુ છે',
  'system.shiftTripBody': 'ગ્રાહકને તમારું લોકેશન દેખાય છે. ખોલવા ટેપ કરો.',
  'system.errOfferTaken': 'આ ઓર્ડર બીજા રાઇડરે લઈ લીધો.',
  'system.errOfferExpired': 'આ ઓફર પૂરી થઈ ગઈ.',
  'system.errOutOfOrder': 'પહેલાં અગાઉનું સ્ટેપ પૂરું કરો.',
  'system.errOtpLocked':
    'ઘણી વાર ખોટો કોડ નાખ્યો. ડિલિવરી પૂરી કરવા સપોર્ટને કૉલ કરો.',
  'system.errTooEarly':
    'દરવાજે થોડી વાર વધુ રાહ જુઓ અને પહેલાં ગ્રાહકને બે વાર કૉલ કરો.',
  'system.errOnTrip': 'ઓફલાઇન થતાં પહેલાં હાલની ડિલિવરી પૂરી કરો.',
  'system.errTripEnded': 'આ ડિલિવરી પહેલેથી પૂરી થઈ ગઈ છે.',
  'system.errValidation': 'તમે જે નાખ્યું તે એક વાર ચેક કરો.',
  'system.errAuth': 'તમારું સેશન પૂરું થયું. ફરી સાઇન ઇન કરો.',
  'system.errForbidden': 'આ એકાઉન્ટ રાઇડર એપ વાપરી શકતું નથી.',
  'system.errRateLimited': 'ઘણી વાર પ્રયત્ન થયો. એક મિનિટ રાહ જોઈ ફરી કરો.',
  'system.errServer': 'અમારી બાજુ કંઈક ગડબડ થઈ. થોડી વારમાં ફરી કરો.',
  'system.errGeneric': 'કંઈક ગડબડ થઈ. ફરી કરો.',
  'system.errNetwork': 'ઇન્ટરનેટ નથી. કનેક્શન ચેક કરીને ફરી કરો.',
  'system.signedOut': 'તમે સાઇન આઉટ થઈ ગયા. ફરી સાઇન ઇન કરો.',
  'system.locationUnavailable': 'લોકેશન મળતું નથી',
  'system.claimTaken': 'આ ઓર્ડર બીજા રાઇડરે પહેલાં લઈ લીધો.',
  'system.claimOffline': 'ઓર્ડર લેવા ઓનલાઇન થાઓ.',
  'system.claimBusy': 'પહેલાં હાલની ડિલિવરી પૂરી કરો.',
  'system.claimFailed': 'આ ઓર્ડર લઈ ન શક્યા. ફરી કરો.',
  'system.lastMinute': 'છેલ્લી મિનિટ',
  'system.minutesLeft': '{n} મિનિટ બાકી',
  'system.blockedBusy': 'પહેલાં હાલની ડિલિવરી પૂરી કરો',
  'system.blockedOffline': 'ઓર્ડર લેવા ઓનલાઇન થાઓ',
  'system.takingAnother': 'બીજો ઓર્ડર લઈ રહ્યા છીએ',
  'system.statusFailed': 'તમારું સ્ટેટસ બદલી ન શક્યા.',
  'system.finishToGoOffline': 'ઓફલાઇન થવા ડિલિવરી પૂરી કરો',
};

export default { en, hi, gu };
