import type { Translations } from '../types';

/** The "are you sure?" step before anything a slip of the thumb must not do. */
const en = {
  'confirm.ok': 'OK',
  'confirm.cancel': 'Cancel',
  'confirm.decline.title': 'Decline this order?',
  'confirm.decline.body':
    'It goes to the next rider and you cannot take it back from here.',
  'confirm.decline.yes': 'Decline',
  'confirm.decline.no': 'Keep it',
  'confirm.unavailable.title': 'Customer not available?',
  'confirm.unavailable.body':
    'Only if you called and waited. This ends the delivery and the support team is told.',
  'confirm.unavailable.yes': 'Yes, end delivery',
  'confirm.unavailable.no': 'Go back',
  'confirm.submit.title': 'Send your application?',
  'confirm.submit.body':
    'You cannot change it while we review it. Check every detail is right.',
  'confirm.resubmit.title': 'Send it again?',
  'confirm.resubmit.body':
    'We will review your changes. You cannot edit while we do.',
  'confirm.submit.yes': 'Send',
  'confirm.submit.no': 'Check again',
  'net.title': 'No internet',
  'net.body': 'Turn on mobile data or Wi-Fi to get orders and save your work.',
  'net.settings': 'Open settings',
  'confirm.leave.title': 'Leave this step?',
  'confirm.leave.body': 'What you typed here is not saved yet. It will be lost.',
  'confirm.leave.yes': 'Leave',
  'confirm.leave.no': 'Keep editing',
} as const;

const hi: Translations<typeof en> = {
  'confirm.ok': 'ठीक है',
  'confirm.cancel': 'रद्द करें',
  'confirm.decline.title': 'यह ऑर्डर मना करें?',
  'confirm.decline.body':
    'यह अगले राइडर के पास जाएगा और यहां से वापस नहीं ले सकते।',
  'confirm.decline.yes': 'मना करें',
  'confirm.decline.no': 'रहने दें',
  'confirm.unavailable.title': 'ग्राहक नहीं मिला?',
  'confirm.unavailable.body':
    'सिर्फ तभी जब आपने कॉल किया और इंतज़ार किया। इससे डिलीवरी खत्म होगी और सपोर्ट टीम को बताया जाएगा।',
  'confirm.unavailable.yes': 'हां, डिलीवरी खत्म करें',
  'confirm.unavailable.no': 'वापस जाएं',
  'confirm.submit.title': 'आवेदन भेजें?',
  'confirm.submit.body':
    'जांच के दौरान आप इसे बदल नहीं सकेंगे। हर जानकारी सही है, देख लें।',
  'confirm.resubmit.title': 'फिर से भेजें?',
  'confirm.resubmit.body': 'हम आपके बदलाव जांचेंगे। तब तक आप बदल नहीं सकेंगे।',
  'confirm.submit.yes': 'भेजें',
  'confirm.submit.no': 'फिर से देखें',
  'net.title': 'इंटरनेट नहीं है',
  'net.body': 'ऑर्डर पाने और अपना काम सेव करने के लिए मोबाइल डेटा या Wi-Fi चालू करें।',
  'net.settings': 'सेटिंग्स खोलें',
  'confirm.leave.title': 'यह कदम छोड़ें?',
  'confirm.leave.body': 'आपने यहाँ जो लिखा है वह अभी सेव नहीं हुआ है। वह मिट जाएगा।',
  'confirm.leave.yes': 'छोड़ें',
  'confirm.leave.no': 'भरते रहें',
};

const gu: Translations<typeof en> = {
  'confirm.ok': 'બરાબર',
  'confirm.cancel': 'રદ કરો',
  'confirm.decline.title': 'આ ઓર્ડરની ના પાડવી છે?',
  'confirm.decline.body': 'તે આગળના રાઇડરને જશે અને અહીંથી પાછો નહીં લઈ શકો.',
  'confirm.decline.yes': 'ના પાડો',
  'confirm.decline.no': 'રહેવા દો',
  'confirm.unavailable.title': 'ગ્રાહક મળ્યા નહીં?',
  'confirm.unavailable.body':
    'ફક્ત ત્યારે જ જ્યારે તમે કૉલ કર્યો અને રાહ જોઈ. આનાથી ડિલિવરી પૂરી થશે અને સપોર્ટ ટીમને જાણ થશે.',
  'confirm.unavailable.yes': 'હા, ડિલિવરી પૂરી કરો',
  'confirm.unavailable.no': 'પાછા જાઓ',
  'confirm.submit.title': 'અરજી મોકલવી છે?',
  'confirm.submit.body':
    'તપાસ દરમિયાન તમે તેને બદલી નહીં શકો. દરેક વિગત સાચી છે તે જોઈ લો.',
  'confirm.resubmit.title': 'ફરી મોકલવી છે?',
  'confirm.resubmit.body':
    'અમે તમારા ફેરફાર તપાસીશું. ત્યાં સુધી તમે બદલી નહીં શકો.',
  'confirm.submit.yes': 'મોકલો',
  'confirm.submit.no': 'ફરી જુઓ',
  'net.title': 'ઇન્ટરનેટ નથી',
  'net.body': 'ઓર્ડર મેળવવા અને તમારું કામ સેવ કરવા મોબાઇલ ડેટા અથવા Wi-Fi ચાલુ કરો.',
  'net.settings': 'સેટિંગ્સ ખોલો',
  'confirm.leave.title': 'આ પગલું છોડશો?',
  'confirm.leave.body': 'તમે અહીં જે લખ્યું છે તે હજી સેવ થયું નથી. તે ભૂંસાઈ જશે.',
  'confirm.leave.yes': 'છોડો',
  'confirm.leave.no': 'ભરતા રહો',
};

export default { en, hi, gu };
