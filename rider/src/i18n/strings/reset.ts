import type { Translations } from '../types';

/** Forgot password: the number, a code to it, a new password. */
const en = {
  'reset.forgot': 'Forgot password?',
  'reset.title': 'Reset your password',
  'reset.lead': 'Enter the number you sign in with. We will check it is yours with a code.',
  'reset.newTitle': 'Choose a new password',
  'reset.newLead': 'You will sign in with this from now on. Any other phone signed in to your account is signed out.',
  'reset.newPassword': 'New password',
  'reset.save': 'Save and sign in',
  'reset.noAccount': 'No rider account uses this number. Check it, or sign up as a new rider.',
  'reset.inactive': 'This account is switched off. Call your manager to turn it back on.',
  'reset.signUp': 'Become a rider',
} as const;

const hi: Translations<typeof en> = {
  'reset.forgot': 'पासवर्ड भूल गए?',
  'reset.title': 'पासवर्ड बदलें',
  'reset.lead': 'वह नंबर डालें जिससे आप साइन इन करते हैं। हम कोड से जाँचेंगे कि नंबर आपका है।',
  'reset.newTitle': 'नया पासवर्ड चुनें',
  'reset.newLead': 'अब से आप इसी से साइन इन करेंगे। आपके अकाउंट से जुड़े दूसरे फ़ोन साइन आउट हो जाएँगे।',
  'reset.newPassword': 'नया पासवर्ड',
  'reset.save': 'सेव करें और साइन इन करें',
  'reset.noAccount': 'इस नंबर से कोई राइडर अकाउंट नहीं है। नंबर जाँचें, या नए राइडर के रूप में साइन अप करें।',
  'reset.inactive': 'यह अकाउंट बंद है। इसे चालू कराने के लिए अपने मैनेजर को कॉल करें।',
  'reset.signUp': 'राइडर बनें',
};

const gu: Translations<typeof en> = {
  'reset.forgot': 'પાસવર્ડ ભૂલી ગયા?',
  'reset.title': 'પાસવર્ડ બદલો',
  'reset.lead': 'જે નંબરથી તમે સાઇન ઇન કરો છો તે નાખો. નંબર તમારો છે એ અમે કોડથી તપાસીશું.',
  'reset.newTitle': 'નવો પાસવર્ડ પસંદ કરો',
  'reset.newLead': 'હવેથી તમે આનાથી સાઇન ઇન કરશો. તમારા એકાઉન્ટવાળા બીજા ફોન સાઇન આઉટ થઈ જશે.',
  'reset.newPassword': 'નવો પાસવર્ડ',
  'reset.save': 'સેવ કરો અને સાઇન ઇન કરો',
  'reset.noAccount': 'આ નંબરથી કોઈ રાઇડર એકાઉન્ટ નથી. નંબર તપાસો, અથવા નવા રાઇડર તરીકે સાઇન અપ કરો.',
  'reset.inactive': 'આ એકાઉન્ટ બંધ છે. ફરી ચાલુ કરાવવા તમારા મેનેજરને કૉલ કરો.',
  'reset.signUp': 'રાઇડર બનો',
};

export default { en, hi, gu };
