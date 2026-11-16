// Mock data for the owner's Submissions page until the submissions API exists.
import { MOCK_SUBMISSIONS } from "./mockAdminSubmissions";

const HOUR = 60 * 60 * 1000;
const ago = (days, hours = 0) => new Date(Date.now() - (days * 24 + hours) * HOUR).toISOString();
const formOf = (id) => MOCK_SUBMISSIONS.find((submission) => submission.id === id).form;

// issues[].field is the form field id to mark; leave it out for issues about a whole section.
// status: "waiting" (not picked up yet), "under_review", "approved" or "rejected".
export const MOCK_MY_SUBMISSIONS = [
  {
    id: "SUB-1042",
    status: "rejected",
    submittedAt: ago(4, 2),
    reviewStartedAt: ago(3, 3),
    decidedAt: ago(0, 5),
    form: formOf("SUB-1042"),
    issues: [
      { section: "Halal status", field: "halalCertificate", label: "Halal certificate", note: "The certificate shows a Section 14 address. Please upload the one for your SS 2 outlet." },
      { section: "Business location", field: "location", label: "Location pin", note: "Your pin is about 180 m from your address. Move it to your shop entrance." },
    ],
  },
  {
    id: "SUB-1030",
    status: "approved",
    submittedAt: ago(12),
    reviewStartedAt: ago(10, 4),
    decidedAt: ago(9),
    form: formOf("SUB-1030"),
    issues: [],
  },
  {
    id: "SUB-1048",
    status: "under_review",
    submittedAt: ago(0, 6),
    reviewStartedAt: ago(0, 2),
    decidedAt: null,
    form: formOf("SUB-1048"),
    issues: [],
  },
];
