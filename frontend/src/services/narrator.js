import { fetchNarration } from "../api/chatApi";
import { createTourVoice } from "./tourVoice";

// The one narrator the app shares, so a new tour always silences the last one.
export const tourVoice = createTourVoice({ fetchLine: fetchNarration });
