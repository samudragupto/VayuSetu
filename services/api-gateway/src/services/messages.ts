import { SUPPORTED_LANGUAGES, isSupportedLanguage } from "../config";

export type MessageKey =
  | "help"
  | "reportAccepted"
  | "reportAcceptedNoLocation"
  | "locationSaved"
  | "locationAttached"
  | "languageSet"
  | "unsupportedMedia"
  | "mediaTooLarge"
  | "rateLimited"
  | "outsideIndia"
  | "statusNone"
  | "statusPending"
  | "statusAnalyzed"
  | "temporaryFailure";

export interface MessageParams {
  shortId?: string;
  city?: string | null;
  aqi?: number | null;
  category?: string | null;
  language?: string;
  limit?: number;
}

type Template = (params: MessageParams) => string;

const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  hi: "Hindi",
  bn: "Bengali",
  ta: "Tamil",
  te: "Telugu",
  mr: "Marathi",
  gu: "Gujarati",
  kn: "Kannada",
  ml: "Malayalam",
  pa: "Punjabi",
};

const EN: Record<MessageKey, Template> = {
  help: () =>
    [
      "Welcome to VayuSetu, the citizen air quality network.",
      "1. Share your location using the WhatsApp attachment menu.",
      "2. Send a photo of the sky or street outside.",
      "You will receive an AI estimate of visibility, haze and likely pollution sources within a minute.",
      "Commands: STATUS for your latest report, LANG HI for Hindi replies, HELP for this message.",
    ].join("\n"),
  reportAccepted: ({ shortId, city }) =>
    `Thank you. Report ${shortId} received${city ? ` for ${city}` : ""}. Our AI is analysing the image and you will get the result shortly.`,
  reportAcceptedNoLocation: ({ shortId }) =>
    `Thank you. Report ${shortId} received. Please share your location (attachment menu, Location) within 30 minutes so we can place it on the map.`,
  locationSaved: ({ city }) =>
    `Location saved${city ? ` near ${city}` : ""}. Now send a photo of the sky or street to report air quality.`,
  locationAttached: ({ shortId, city }) =>
    `Location added to report ${shortId}${city ? ` (${city})` : ""}. Thank you for helping map air quality.`,
  languageSet: ({ language }) => `Replies will now be sent in ${LANGUAGE_NAMES[language ?? "en"] ?? language}.`,
  unsupportedMedia: () => "Only JPEG, PNG or WebP photos can be analysed. Please send a photo of the outdoor scene.",
  mediaTooLarge: ({ limit }) => `The image is too large (limit ${Math.round((limit ?? 0) / (1024 * 1024))} MB). Please send a smaller photo.`,
  rateLimited: ({ limit }) => `You have reached the limit of ${limit} reports per hour. Please try again later.`,
  outsideIndia: () => "VayuSetu currently covers locations in India. The location you shared is outside the supported area.",
  statusNone: () => "No reports found for this number yet. Send a photo of the sky to create your first report.",
  statusPending: ({ shortId }) => `Report ${shortId} is still being analysed. You will receive the result shortly.`,
  statusAnalyzed: ({ shortId, aqi, category, city }) =>
    `Report ${shortId}${city ? ` (${city})` : ""}: estimated AQI ${aqi ?? "n/a"}${category ? `, ${category.replace(/_/g, " ")}` : ""}.`,
  temporaryFailure: () => "We could not process your message right now. Please try again in a few minutes.",
};

const HI: Record<MessageKey, Template> = {
  help: () =>
    [
      "VayuSetu नागरिक वायु गुणवत्ता नेटवर्क में आपका स्वागत है।",
      "1. WhatsApp अटैचमेंट मेनू से अपनी लोकेशन साझा करें।",
      "2. बाहर के आसमान या सड़क की एक फोटो भेजें।",
      "एक मिनट के भीतर आपको दृश्यता, धुंध और संभावित प्रदूषण स्रोतों का AI अनुमान मिलेगा।",
      "कमांड: STATUS (आपकी नवीनतम रिपोर्ट), LANG EN (अंग्रेज़ी में उत्तर), HELP (यह संदेश)।",
    ].join("\n"),
  reportAccepted: ({ shortId, city }) =>
    `धन्यवाद। रिपोर्ट ${shortId}${city ? ` (${city})` : ""} प्राप्त हुई। हमारा AI फोटो का विश्लेषण कर रहा है, परिणाम शीघ्र मिलेगा।`,
  reportAcceptedNoLocation: ({ shortId }) =>
    `धन्यवाद। रिपोर्ट ${shortId} प्राप्त हुई। कृपया 30 मिनट के भीतर अपनी लोकेशन साझा करें ताकि हम इसे मानचित्र पर दिखा सकें।`,
  locationSaved: ({ city }) => `लोकेशन सहेज ली गई${city ? ` (${city} के पास)` : ""}। अब वायु गुणवत्ता रिपोर्ट के लिए आसमान या सड़क की फोटो भेजें।`,
  locationAttached: ({ shortId, city }) => `रिपोर्ट ${shortId} में लोकेशन जोड़ दी गई${city ? ` (${city})` : ""}। सहयोग के लिए धन्यवाद।`,
  languageSet: ({ language }) => `अब उत्तर ${LANGUAGE_NAMES[language ?? "hi"] ?? language} में भेजे जाएंगे।`,
  unsupportedMedia: () => "केवल JPEG, PNG या WebP फोटो का विश्लेषण किया जा सकता है। कृपया बाहरी दृश्य की फोटो भेजें।",
  mediaTooLarge: ({ limit }) => `फोटो बहुत बड़ी है (सीमा ${Math.round((limit ?? 0) / (1024 * 1024))} MB)। कृपया छोटी फोटो भेजें।`,
  rateLimited: ({ limit }) => `आप प्रति घंटे ${limit} रिपोर्ट की सीमा तक पहुंच गए हैं। कृपया बाद में पुनः प्रयास करें।`,
  outsideIndia: () => "VayuSetu अभी भारत के स्थानों को कवर करता है। साझा की गई लोकेशन समर्थित क्षेत्र के बाहर है।",
  statusNone: () => "इस नंबर से अभी तक कोई रिपोर्ट नहीं मिली। पहली रिपोर्ट के लिए आसमान की फोटो भेजें।",
  statusPending: ({ shortId }) => `रिपोर्ट ${shortId} का विश्लेषण अभी जारी है। परिणाम शीघ्र मिलेगा।`,
  statusAnalyzed: ({ shortId, aqi, category, city }) =>
    `रिपोर्ट ${shortId}${city ? ` (${city})` : ""}: अनुमानित AQI ${aqi ?? "n/a"}${category ? `, ${category.replace(/_/g, " ")}` : ""}।`,
  temporaryFailure: () => "हम अभी आपका संदेश संसाधित नहीं कर सके। कृपया कुछ मिनट बाद पुनः प्रयास करें।",
};

const CATALOG: Record<string, Record<MessageKey, Template>> = { en: EN, hi: HI };

/** Render a user-facing WhatsApp message in the requested language (English fallback). */
export function renderMessage(language: string, key: MessageKey, params: MessageParams = {}): string {
  const catalog = CATALOG[language] ?? EN;
  return catalog[key](params);
}

/** Parse "LANG HI", "language: hindi", "भाषा hi" style commands. */
export function parseLanguageCommand(body: string): string | null {
  const match = body.trim().match(/^(?:lang|language|bhasha|भाषा)\s*[:=]?\s*([a-z]{2,10})$/i);
  if (!match) {
    return null;
  }
  const requested = match[1]?.toLowerCase() ?? "";
  if (isSupportedLanguage(requested)) {
    return requested;
  }
  const byName = SUPPORTED_LANGUAGES.find((code) => LANGUAGE_NAMES[code]?.toLowerCase() === requested);
  return byName ?? null;
}

export function shortReportId(reportId: string): string {
  return reportId.slice(0, 8).toUpperCase();
}
