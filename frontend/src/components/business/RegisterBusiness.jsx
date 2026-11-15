import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Send } from "lucide-react";
import Logo from "../../assets/foodsightLogo.png";
import DarkModeLogo from "../../assets/foodsightLogoDarkMode.png";
import {
  AMBIANCES, AREAS, BUSINESS_STATUSES, BUSINESS_STEPS, BUSINESS_STYLES, CITY, CUISINES, DOCUMENT_TYPES, FACILITY_GROUPS,
  HALAL_STATUSES, MAX_AMBIANCES, MAX_CUISINES, MAX_DESCRIPTION, MAX_TARGET_SEGMENTS, PHOTO_TYPES, RESTAURANT_TYPES,
  SERVICE_STYLES, TARGET_SEGMENTS, YES_NO, businessStepOneErrors, businessStepTwoErrors, isChain, todayIso,
} from "../../services/businessForm";
import {
  CheckboxGroups, ChoiceGroup, DateInput, FieldNote, FileUpload, FormSection, MultiPicker, PhoneInput, SelectInput,
  TextArea, TextInput,
} from "./BusinessFields";
import LocationPicker from "./LocationPicker";
import OpeningHours from "./OpeningHours";
import { ReviewDetails, SubmittedNotice } from "./ReviewDetails";
import "../../styles/business.css";

const AREA_OPTIONS = AREAS.map((area) => ({ value: area, label: area }));
const CUISINE_OPTIONS = CUISINES.map((cuisine) => ({ value: cuisine, label: cuisine }));
const STEP_CHECKS = [businessStepOneErrors, businessStepTwoErrors];

function Stepper({ step, onStep }) {
  return (
    <ol className="business-stepper" aria-label="Registration steps">
      {BUSINESS_STEPS.map((label, index) => {
        const state = index < step ? "is-done" : index === step ? "is-current" : "";
        return (
          <li key={label} className={state} aria-current={index === step ? "step" : undefined}>
            {index < step ? (
              <button type="button" className="business-step-link" onClick={() => onStep(index)}>
                <span className="business-step-number"><Check aria-hidden="true" /></span>
                <span className="business-step-label">{label}</span>
              </button>
            ) : (
              <>
                <span className="business-step-number">{index + 1}</span>
                <span className="business-step-label">{label}</span>
              </>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function RegisterBusiness({ form, setForm, step, setStep, darkMode = false }) {
  // Errors only show for steps whose Next has been pressed.
  const [checkedSteps, setCheckedSteps] = useState([]);
  const scrollRef = useRef(null);
  // The email is also checked on blur, before Next.
  const [emailLeft, setEmailLeft] = useState(false);
  const check = STEP_CHECKS[step];
  const allErrors = check ? check(form) : {};
  const errors = checkedSteps.includes(step)
    ? allErrors
    : step === 0 && emailLeft && form.businessEmail.trim() && allErrors.businessEmail ? { businessEmail: allErrors.businessEmail } : {};
  const set = (field) => (value) => setForm((previous) => ({ ...previous, [field]: value }));
  const text = (field) => ({
    value: form[field],
    error: errors[field],
    onChange: (event) => set(field)(event.target.value),
  });

  const [submitted, setSubmitted] = useState(false);
  // Scrolled to after the target step renders (e.g. from an Edit link).
  const pendingField = useRef(null);

  const goTo = (next, field = null) => {
    pendingField.current = field;
    setStep(next);
    scrollRef.current?.scrollTo({ top: 0 });
  };

  useEffect(() => {
    const id = pendingField.current;
    if (!id) return;
    pendingField.current = null;
    const field = document.getElementById(id) ?? document.getElementById(`${id}-error`);
    field?.scrollIntoView({ block: "center" });
    field?.focus({ preventScroll: true });
  }, [step]);

  const handleSubmit = () => {
    for (const [index, stepCheck] of STEP_CHECKS.entries()) {
      const first = Object.keys(stepCheck(form))[0];
      if (first) {
        setCheckedSteps((previous) => (previous.includes(index) ? previous : [...previous, index]));
        goTo(index, first);
        return;
      }
    }
    // TODO: send the registration once the backend has an endpoint for it; nothing leaves the browser yet.
    setSubmitted(true);
    scrollRef.current?.scrollTo({ top: 0 });
  };

  const handleNext = () => {
    if (!check) return;
    const found = check(form);
    setCheckedSteps((previous) => (previous.includes(step) ? previous : [...previous, step]));
    const first = Object.keys(found)[0];
    if (!first) {
      goTo(step + 1);
      return;
    }
    // Section-wide errors (e.g. no open day) have no field, only the message.
    const field = document.getElementById(first) ?? document.getElementById(`${first}-error`);
    field?.scrollIntoView({ behavior: "smooth", block: "center" });
    field?.focus({ preventScroll: true });
  };


  return (
    <main className="business-area">
      <div className="business-card" ref={scrollRef}>
        <header className="business-header">
          <img src={darkMode ? DarkModeLogo : Logo} alt="FoodSight" className="business-logo" />
          <h1>Register a Business Account</h1>
          <Stepper step={step} onStep={goTo} />
        </header>

        {step === 0 ? (
          <form className="business-form" noValidate onSubmit={(event) => { event.preventDefault(); handleNext(); }}>
            <FormSection title="Store manager information">
              <TextInput id="managerName" label="Full name (as on IC)" required placeholder="e.g. Aisyah binti Rahman" autoComplete="name" {...text("managerName")} />
              <PhoneInput id="managerPhone" label="Contact phone" required placeholder="e.g. 12-345 6789" autoComplete="tel-national" value={form.managerPhone} onChange={set("managerPhone")} error={errors.managerPhone} />
            </FormSection>

            <FormSection title="General information">
              <TextInput id="businessName" label="Business name" required placeholder="e.g. Cafe Foodsight" autoComplete="organization" {...text("businessName")} />
              <SelectInput id="businessStyle" label="Business style" required options={BUSINESS_STYLES} value={form.businessStyle} onChange={set("businessStyle")} />
              {isChain(form.businessStyle) && (
                <>
                  <TextInput id="brandName" label="Brand name" required placeholder="Enter brand name" {...text("brandName")} />
                  <div className="business-grid-spacer" aria-hidden="true" />
                </>
              )}
              <PhoneInput id="businessPhone" label="Business phone" required placeholder="e.g. 3-7955 1234" value={form.businessPhone} onChange={set("businessPhone")} error={errors.businessPhone} />
              <TextInput id="businessEmail" label="Business email" required type="email" placeholder="e.g. foodsight@gmail.com" autoComplete="email" {...text("businessEmail")} onBlur={() => setEmailLeft(true)} />
              <SelectInput id="restaurantType" label="Restaurant type" required placeholder="Select restaurant type" options={RESTAURANT_TYPES} value={form.restaurantType} onChange={set("restaurantType")} error={errors.restaurantType} />
              <SelectInput id="businessStatus" label="Status" required options={BUSINESS_STATUSES} value={form.businessStatus} onChange={set("businessStatus")} error={errors.businessStatus} />
              <TextInput id="website" label="Website or social page" type="url" placeholder="https://" autoComplete="url" {...text("website")} />
            </FormSection>

            <FormSection title="Business location">
              <TextInput id="address" label="Address" required wide placeholder="e.g. 123, Jalan Tun Razak, Taman Melawati" autoComplete="street-address" {...text("address")} />
              <TextInput
                id="postcode" label="Postcode" required inputMode="numeric" maxLength={5} placeholder="e.g. 12345" autoComplete="postal-code"
                value={form.postcode} error={errors.postcode}
                onChange={(event) => set("postcode")(event.target.value.replace(/\D/g, ""))}
              />
              <SelectInput id="area" label="Area" required placeholder="Select area" options={AREA_OPTIONS} value={form.area} onChange={set("area")} error={errors.area} />
              <TextInput id="city" label="City" value={CITY} readOnly tabIndex={-1} />
              <div className="business-field is-wide">
                <span className="business-label">
                  Location<span className="business-required" aria-hidden="true">*</span>
                </span>
                <LocationPicker id="location" value={form.location} onChange={set("location")} darkMode={darkMode} error={errors.location} />
                {errors.location && <p id="location-error" className="business-error" role="alert">{errors.location}</p>}
              </div>
            </FormSection>

            <FormSection title="Business verification">
              <TextInput id="ssmNumber" label="SSM registration number" required wide inputMode="numeric" placeholder="e.g. 123456789123" {...text("ssmNumber")} />
              <FileUpload
                id="ssmCertificate" label="SSM certificate" title="SSM Certificate" required
                hint="PDF, JPG or PNG, up to 10 MB" types={DOCUMENT_TYPES}
                file={form.ssmCertificate} onChange={set("ssmCertificate")} error={errors.ssmCertificate}
              />
              <FileUpload
                id="premisesLicence" label="MBPJ food-premises licence" title="MBPJ Food-Premises Licence" optional
                hint="PDF, JPG or PNG, up to 10 MB" types={DOCUMENT_TYPES}
                file={form.premisesLicence} onChange={set("premisesLicence")}
              />
              <FileUpload
                id="storefrontPhoto" label="Storefront photo" title="Storefront photo" required
                hint="JPG or PNG, up to 10 MB" types={PHOTO_TYPES}
                file={form.storefrontPhoto} onChange={set("storefrontPhoto")} error={errors.storefrontPhoto}
              />
            </FormSection>

            <FormSection title="Halal status">
              <ChoiceGroup
                id="halalStatus" label="Halal status" required options={HALAL_STATUSES}
                value={form.halalStatus} onChange={set("halalStatus")} error={errors.halalStatus}
              />
              {form.halalStatus === "halal_certified" && (
                <>
                  <div className="business-field is-wide">
                    <FileUpload
                      id="halalCertificate" title="Halal Certificate" required
                      hint="PDF, JPG or PNG, up to 10 MB" types={DOCUMENT_TYPES}
                      file={form.halalCertificate} onChange={set("halalCertificate")} error={errors.halalCertificate}
                    />
                    <FieldNote>A valid certificate issued by JAKIM (Jabatan Kemajuan Islam Malaysia).</FieldNote>
                  </div>
                  <DateInput
                    id="halalExpiry" label="Certificate expiration date" required min={todayIso()}
                    value={form.halalExpiry} onChange={set("halalExpiry")} error={errors.halalExpiry}
                  />
                </>
              )}
              {form.halalStatus === "not_halal" && (
                <>
                  <ChoiceGroup
                    id="sellsPork" label="Does this store sell any pork?" required options={YES_NO} columns={3}
                    value={form.sellsPork} onChange={set("sellsPork")} error={errors.sellsPork}
                  />
                  <ChoiceGroup
                    id="servesAlcohol" label="Does this store offer any item containing alcohol?" required options={YES_NO} columns={3}
                    value={form.servesAlcohol} onChange={set("servesAlcohol")} error={errors.servesAlcohol}
                  />
                </>
              )}
            </FormSection>
          </form>
        ) : step === 1 ? (
          <form className="business-form" noValidate onSubmit={(event) => { event.preventDefault(); handleNext(); }}>
            <OpeningHours hours={form.hours} onChange={set("hours")} errors={errors} />

            <FormSection title="Food & dining experience">
              <MultiPicker
                id="cuisines" label="Cuisines served" required hint={`Pick up to ${MAX_CUISINES}`} placeholder="Select cuisines"
                options={CUISINE_OPTIONS} value={form.cuisines} onChange={set("cuisines")} max={MAX_CUISINES} error={errors.cuisines}
              />
              <SelectInput id="serviceStyle" label="Service style" required placeholder="Select service style" options={SERVICE_STYLES} value={form.serviceStyle} onChange={set("serviceStyle")} error={errors.serviceStyle} />
              <TextInput
                id="averageSpend" label="Average spend per person (RM)" required inputMode="decimal" placeholder="e.g. 12.00"
                value={form.averageSpend} error={errors.averageSpend}
                onChange={(event) => set("averageSpend")(event.target.value.replace(/[^\d.]/g, ""))}
                onBlur={() => {
                  const amount = Number(form.averageSpend);
                  if (form.averageSpend && /^\d+(\.\d*)?$/.test(form.averageSpend) && amount > 0) set("averageSpend")(amount.toFixed(2));
                }}
              />
              <MultiPicker
                id="targetSegments" label="Who usually dines here?" required hint={`Pick up to ${MAX_TARGET_SEGMENTS}`} placeholder="Select diners" wide={false}
                options={TARGET_SEGMENTS} value={form.targetSegments} onChange={set("targetSegments")} max={MAX_TARGET_SEGMENTS} error={errors.targetSegments}
              />
              <MultiPicker
                id="ambiance" label="Ambiance" required hint={`Pick up to ${MAX_AMBIANCES}`} placeholder="Select ambiance" wide={false}
                options={AMBIANCES} value={form.ambiance} onChange={set("ambiance")} max={MAX_AMBIANCES} error={errors.ambiance}
              />
              <TextArea
                id="description" label="Short description of restaurant" required wide maxRows={4} maxLength={MAX_DESCRIPTION}
                placeholder="Short description of restaurant" {...text("description")}
              />
            </FormSection>

            <section className="business-section" aria-labelledby="facilities-title">
              <h2 id="facilities-title">Facilities &amp; services</h2>
              <CheckboxGroups groups={FACILITY_GROUPS} value={form.facilities} onChange={set("facilities")} />
            </section>
          </form>
        ) : submitted ? (
          <SubmittedNotice email={form.businessEmail} />
        ) : (
          <ReviewDetails form={form} onEdit={goTo} />
        )}

        {check && (
          <footer className={`business-actions${step > 0 ? " has-back" : ""}`}>
            {step > 0 && (
              <button type="button" className="business-back-btn" onClick={() => goTo(step - 1)}>
                <ArrowLeft aria-hidden="true" />
                Back
              </button>
            )}
            <button type="button" className="business-next-btn" onClick={handleNext}>
              Next
              <ArrowRight aria-hidden="true" />
            </button>
          </footer>
        )}
        {!check && !submitted && (
          <footer className="business-actions has-back">
            <button type="button" className="business-back-btn" onClick={() => goTo(step - 1)}>
              <ArrowLeft aria-hidden="true" />
              Back
            </button>
            <button type="button" className="business-next-btn" onClick={handleSubmit}>
              <Send aria-hidden="true" />
              Submit for review
            </button>
          </footer>
        )}
      </div>
    </main>
  );
}

export default RegisterBusiness;
