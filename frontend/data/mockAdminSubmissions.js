// Mock data for the admin pages until the submissions API exists. Dates are relative to page load.
const HOUR = 60 * 60 * 1000;
const ago = (days, hours = 0) => new Date(Date.now() - (days * 24 + hours) * HOUR).toISOString();

const weekdays = (from, to, saturday = null, sunday = null) => [
  ...Array.from({ length: 5 }, () => ({ open: true, allDay: false, periods: [{ from, to }] })),
  saturday ? { open: true, allDay: false, periods: [saturday] } : { open: false, allDay: false, periods: [] },
  sunday ? { open: true, allDay: false, periods: [sunday] } : { open: false, allDay: false, periods: [] },
];

const pdf = (name, kb) => ({ name, size: kb * 1024, type: "application/pdf" });
const jpg = (name, kb) => ({ name, size: kb * 1024, type: "image/jpeg" });

function submission({ id, submittedAt, status = "waiting", decidedAt = null, decidedBy = null, review = {}, ...form }) {
  const slug = form.businessName.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return {
    id,
    submittedAt,
    status,
    decidedAt,
    decidedBy,
    review,
    form: {
      businessStyle: "independent", brandName: "", businessStatus: "OPERATIONAL", website: "",
      ssmCertificate: pdf(`ssm-${slug}.pdf`, 840), premisesLicence: pdf("mbpj-licence-2026.pdf", 1126),
      storefrontPhoto: jpg("storefront.jpg", 2458),
      halalStatus: "halal_not_certified", halalCertificate: null, halalExpiry: "", sellsPork: "", servesAlcohol: "",
      hours: weekdays("08:00", "22:00", { from: "08:00", to: "22:00" }),
      cuisines: ["Malaysian"], serviceStyle: "table_service", targetSegments: ["local_residents"], ambiance: ["casual"],
      averageSpend: "15", facilities: ["Dine-in", "Takeout"],
      ...form,
    },
  };
}

const checked = (keys) => Object.fromEntries(keys.map((key) => [key, { state: "checked", note: "" }]));
const STARTED = checked(["managerName", "managerPhone", "businessName", "businessStyle"]);

export const MOCK_REVIEWER = "Nurul Huda";

export const MOCK_GRAPH_RESTAURANTS = 1000;

// New submissions per week, oldest first; the last entry is the current week.
export const MOCK_WEEKLY_SUBMISSIONS = [9, 12, 8, 14, 11, 16, 13, 18];

export const MOCK_SUBMISSIONS = [
  submission({
    id: "SUB-1042", submittedAt: ago(4, 2),
    managerName: "Aisyah binti Rahman", managerPhone: "12-345 6789",
    businessName: "Kedai Kopi Sinar", businessPhone: "3-7865 2210", businessEmail: "hello@kedaikopisinar.my",
    restaurantType: "kopitiam", website: "instagram.com/kedaikopisinar",
    address: "12, Jalan SS 2/24", postcode: "47300", area: "SS 2", location: { latitude: 3.1178, longitude: 101.6213 },
    ssmNumber: "202301012345",
    halalStatus: "halal_certified", halalCertificate: pdf("jakim-halal-cert.pdf", 620), halalExpiry: "2027-03-31",
    hours: [
      ...Array.from({ length: 5 }, () => ({ open: true, allDay: false, periods: [{ from: "07:00", to: "15:00" }, { from: "17:00", to: "22:00" }] })),
      { open: true, allDay: false, periods: [{ from: "08:00", to: "23:30" }] },
      { open: false, allDay: false, periods: [] },
    ],
    cuisines: ["Chinese (Malaysia)", "Malaysian"], serviceStyle: "table_service", averageSpend: "12",
    targetSegments: ["office_workers", "local_residents", "families"], ambiance: ["traditional", "casual"],
    description: "Family-run kopitiam since 1987 serving charcoal-toasted kaya bread, half-boiled eggs and nasi lemak, with kopi brewed the old way.",
    facilities: ["Dine-in", "Takeout", "Delivery", "Breakfast", "Lunch", "Dinner", "Coffee", "Good for Children", "Good for Groups", "Wheelchair Accessible", "Debit Card", "Contactless Payment"],
    review: {
      ...checked(["managerName", "managerPhone", "businessName", "businessStyle", "businessPhone", "businessEmail", "restaurantType", "businessStatus", "website", "address", "postcode", "area", "ssmNumber", "ssmCertificate", "premisesLicence", "storefrontPhoto", "halalStatus", "halalExpiry", "hours"]),
      location: { state: "flagged", note: "The pin is on the next street. Please move it to your shop entrance on Jalan SS 2/24." },
      halalCertificate: { state: "flagged", note: "The certificate is for a premise in Section 14. Please upload the certificate for your SS 2 outlet." },
    },
  }),
  submission({
    id: "SUB-1043", submittedAt: ago(3, 5),
    managerName: "Rosli Ahmad", managerPhone: "19-882 4410",
    businessName: "Warung Mak Teh", businessPhone: "19-882 4410", businessEmail: "warungmakteh@gmail.com",
    restaurantType: "warung", address: "Lot 5, Jalan 14/22", postcode: "46100", area: "Seksyen 14", location: { latitude: 3.1105, longitude: 101.6355 },
    ssmNumber: "202201034411", hours: weekdays("06:30", "14:00", { from: "06:30", to: "14:00" }),
    cuisines: ["Malay"], serviceStyle: "self_service", averageSpend: "9", ambiance: ["no_frills"],
    description: "Nasi campur, lontong and kuih every morning, cooked by Mak Teh herself.",
    facilities: ["Dine-in", "Takeout", "Breakfast", "Lunch", "Cash Only"],
  }),
  submission({
    id: "SUB-1044", submittedAt: ago(3, 1), review: STARTED,
    managerName: "Jason Lee", managerPhone: "16-230 7781",
    businessName: "Brew & Bread PJ", businessPhone: "3-7728 1190", businessEmail: "hi@brewandbread.my",
    restaurantType: "cafe", website: "https://brewandbread.my",
    address: "28, Jalan SS 21/37", postcode: "47400", area: "SS 21 (Damansara Uptown, Damansara Utama)", location: { latitude: 3.1343, longitude: 101.6232 },
    ssmNumber: "202101056782", hours: weekdays("08:00", "18:00", { from: "09:00", to: "20:00" }, { from: "09:00", to: "20:00" }),
    cuisines: ["Coffee", "Bakery", "Western"], serviceStyle: "counter_service", averageSpend: "28",
    targetSegments: ["young_adults", "students"], ambiance: ["aesthetic", "cosy"],
    description: "Speciality coffee and sourdough baked in-house every morning.",
    facilities: ["Dine-in", "Takeout", "Breakfast", "Brunch", "Coffee", "Dessert", "Credit Card", "Contactless Payment"],
  }),
  submission({
    id: "SUB-1045", submittedAt: ago(1, 3),
    managerName: "Siti Mariam", managerPhone: "12-675 0923",
    businessName: "Restoran Seri Melur", businessPhone: "3-7956 2201", businessEmail: "serimelur.pj@gmail.com",
    restaurantType: "casual_restaurant", address: "3, Jalan 17/45", postcode: "46400", area: "Seksyen 17 (Happy Garden)", location: { latitude: 3.1262, longitude: 101.6401 },
    ssmNumber: "201901078812", halalStatus: "halal_certified", halalCertificate: pdf("halal-seri-melur.pdf", 540), halalExpiry: "2027-08-15",
    cuisines: ["Malay", "Nyonya"], targetSegments: ["families", "large_groups"], ambiance: ["traditional"],
    description: "Home-style Malay and Nyonya dishes, with ikan bakar on weekends.",
    facilities: ["Dine-in", "Takeout", "Lunch", "Dinner", "Good for Groups", "Free Street Parking"],
  }),
  submission({
    id: "SUB-1046", submittedAt: ago(1, 1),
    managerName: "Kenji Tan", managerPhone: "11-2045 8830",
    businessName: "Ramen Hikari", businessPhone: "11-2045 8830", businessEmail: "ramenhikari@outlook.com",
    restaurantType: "casual_restaurant", address: "G-12, Jalan SS 15/4", postcode: "47500", area: "SS 22 (Damansara Jaya)", location: { latitude: 3.1278, longitude: 101.6170 },
    ssmNumber: "202301098120", halalStatus: "not_halal", sellsPork: "yes", servesAlcohol: "yes",
    hours: weekdays("11:30", "22:00", { from: "11:30", to: "22:30" }, { from: "11:30", to: "22:30" }),
    cuisines: ["Japanese"], averageSpend: "35", targetSegments: ["young_adults", "couples"], ambiance: ["modern"],
    description: "Tonkotsu and shoyu ramen with broth simmered for 18 hours.",
    facilities: ["Dine-in", "Lunch", "Dinner", "Beer", "Credit Card"],
  }),
  submission({
    id: "SUB-1047", submittedAt: ago(0, 20), review: STARTED,
    managerName: "Muthu Raj", managerPhone: "17-339 2104",
    businessName: "Roti Canai Corner", businessPhone: "17-339 2104", businessEmail: "roticanaicorner@gmail.com",
    restaurantType: "mamak", address: "7, Jalan SS 2/64", postcode: "47300", area: "SS 2", location: { latitude: 3.1196, longitude: 101.6224 },
    ssmNumber: "202001044390", halalStatus: "halal_certified", halalCertificate: pdf("halal-rcc.pdf", 480), halalExpiry: "2027-01-20",
    hours: Array.from({ length: 7 }, () => ({ open: true, allDay: true, periods: [] })),
    cuisines: ["Indian Muslim", "Malaysian"], averageSpend: "10", targetSegments: ["late_night_crowd", "students"], ambiance: ["lively"],
    description: "Open 24 hours with roti canai, nasi kandar and teh tarik.",
    facilities: ["Dine-in", "Takeout", "Delivery", "Breakfast", "Lunch", "Dinner", "Live Sports", "Cash Only"],
  }),
  submission({
    id: "SUB-1048", submittedAt: ago(0, 6), review: STARTED,
    managerName: "Chloe Ng", managerPhone: "12-901 5567",
    businessName: "Bubble Tea Lab", businessPhone: "12-901 5567", businessEmail: "hello@bubbletealab.my",
    restaurantType: "drinks_shop", address: "15, Jalan SS 22/25", postcode: "47400", area: "SS 22 (Damansara Jaya)", location: { latitude: 3.1301, longitude: 101.6155 },
    ssmNumber: "202401011256", hours: weekdays("11:00", "22:00", { from: "11:00", to: "23:00" }, { from: "11:00", to: "23:00" }),
    cuisines: ["Bubble Tea"], serviceStyle: "counter_service", averageSpend: "14", targetSegments: ["students", "young_adults"], ambiance: ["modern"],
    description: "Brown sugar boba and fruit teas made to order.",
    facilities: ["Takeout", "Delivery", "Contactless Payment"],
  }),
  submission({
    id: "SUB-1049", submittedAt: ago(0, 2), review: STARTED,
    managerName: "Wong Mei Ling", managerPhone: "13-448 2290",
    businessName: "Dim Sum Garden", businessPhone: "3-7960 8812", businessEmail: "dimsumgarden.pj@gmail.com",
    restaurantType: "casual_restaurant", address: "2, Jalan 52/18", postcode: "46200", area: "Seksyen 52 (PJ State)", location: { latitude: 3.0969, longitude: 101.6448 },
    ssmNumber: "201801067734", halalStatus: "not_halal", sellsPork: "yes", servesAlcohol: "no",
    hours: weekdays("07:00", "15:00", { from: "07:00", to: "15:00" }, { from: "07:00", to: "15:00" }),
    cuisines: ["Chinese (Hong Kong)"], averageSpend: "25", targetSegments: ["families", "seniors"], ambiance: ["lively"],
    description: "Handmade dim sum steamed fresh from 7 am.",
    facilities: ["Dine-in", "Takeout", "Breakfast", "Brunch", "Lunch", "Good for Groups"],
  }),
  submission({
    id: "SUB-1050", submittedAt: ago(5, 4),
    managerName: "Faizal Hassan", managerPhone: "18-221 7345",
    businessName: "Nasi Kandar Seri Bayu", businessPhone: "3-7781 4402", businessEmail: "seribayu.nk@gmail.com",
    restaurantType: "mamak", address: "9, Jalan SS 24/2", postcode: "47301", area: "SS 24 (Taman Megah)", location: { latitude: 3.1175, longitude: 101.6062 },
    ssmNumber: "201701023391", halalStatus: "halal_certified", halalCertificate: pdf("halal-seri-bayu.pdf", 512), halalExpiry: "2026-12-31",
    cuisines: ["Indian Muslim"], averageSpend: "13", targetSegments: ["office_workers"], ambiance: ["no_frills"],
    description: "Nasi kandar with over 20 curries and fried chicken.",
    facilities: ["Dine-in", "Takeout", "Lunch", "Dinner"],
  }),
  submission({
    id: "SUB-1051", submittedAt: ago(2, 6),
    managerName: "Hana Yusof", managerPhone: "14-772 3019",
    businessName: "Kafe Daun Pandan", businessPhone: "14-772 3019", businessEmail: "daunpandan.kafe@gmail.com",
    restaurantType: "cafe", address: "21, Jalan PJU 7/3", postcode: "47810", area: "PJU 7 (Mutiara Damansara)", location: { latitude: 3.1588, longitude: 101.6110 },
    ssmNumber: "202201088765", halalStatus: "halal_not_certified",
    cuisines: ["Malaysian", "Desserts"], averageSpend: "18", targetSegments: ["young_adults", "couples"], ambiance: ["cosy", "nature"],
    description: "Pandan cakes, onde-onde and local coffee in a garden setting.",
    facilities: ["Dine-in", "Takeout", "Dessert", "Coffee", "Outdoor Seating"],
  }),
  submission({
    id: "SUB-1052", submittedAt: ago(0, 1),
    managerName: "Marco Lim", managerPhone: "16-554 0981",
    businessName: "Pizza Lorong", businessPhone: "16-554 0981", businessEmail: "orders@pizzalorong.my",
    restaurantType: "fast_food", address: "4, Jalan 19/1", postcode: "46300", area: "Seksyen 19", location: { latitude: 3.1210, longitude: 101.6302 },
    ssmNumber: "202501004478", halalStatus: "not_halal", sellsPork: "yes", servesAlcohol: "yes",
    cuisines: ["Pizza", "Italian"], serviceStyle: "counter_service", averageSpend: "30", targetSegments: ["young_adults"], ambiance: ["lively"],
    description: "Wood-fired Neapolitan pizza by the slice.",
    facilities: ["Dine-in", "Takeout", "Delivery", "Beer", "Credit Card"],
  }),
  submission({
    id: "SUB-1053", submittedAt: ago(0, 0.3),
    managerName: "Arjun Pillai", managerPhone: "12-889 3301",
    businessName: "Thosai Thambi", businessPhone: "12-889 3301", businessEmail: "thosaithambi@gmail.com",
    restaurantType: "casual_restaurant", address: "11, Jalan 13/6", postcode: "46200", area: "Seksyen 13", location: { latitude: 3.1145, longitude: 101.6380 },
    ssmNumber: "202501009910", halalStatus: "halal_not_certified",
    cuisines: ["Indian", "Vegetarian"], averageSpend: "12", targetSegments: ["families"], ambiance: ["casual"],
    description: "South Indian banana-leaf rice and crispy thosai.",
    facilities: ["Dine-in", "Takeout", "Breakfast", "Lunch", "Vegetarian Options"],
  }),

  submission({
    id: "SUB-1030", submittedAt: ago(12), status: "approved", decidedAt: ago(9), decidedBy: MOCK_REVIEWER,
    managerName: "Tan Wei Ming", managerPhone: "12-334 8890",
    businessName: "Kopi Tiam Lama", businessPhone: "3-7955 1234", businessEmail: "kopitiamlama@gmail.com",
    restaurantType: "kopitiam", address: "6, Jalan SS 2/55", postcode: "47300", area: "SS 2", location: { latitude: 3.1201, longitude: 101.6205 },
    ssmNumber: "201501012233", halalStatus: "halal_certified", halalCertificate: pdf("halal-ktl.pdf", 600), halalExpiry: "2027-05-30",
    cuisines: ["Chinese (Malaysia)"], averageSpend: "11", facilities: ["Dine-in", "Takeout", "Breakfast", "Coffee"],
  }),
  submission({
    id: "SUB-1031", submittedAt: ago(14), status: "approved", decidedAt: ago(11), decidedBy: "Daniel Lim",
    managerName: "Nur Aina", managerPhone: "13-220 7731",
    businessName: "Gerai Laksa Aina", businessPhone: "13-220 7731", businessEmail: "laksaaina@gmail.com",
    restaurantType: "hawker_stall", address: "Medan Selera Seksyen 14", postcode: "46100", area: "Seksyen 14", location: { latitude: 3.1110, longitude: 101.6362 },
    ssmNumber: "202001065512", cuisines: ["Malay"], averageSpend: "8", facilities: ["Dine-in", "Takeout", "Lunch", "Cash Only"],
  }),
  submission({
    id: "SUB-1032", submittedAt: ago(16), status: "approved", decidedAt: ago(13), decidedBy: MOCK_REVIEWER,
    managerName: "David Chong", managerPhone: "17-665 2201",
    businessName: "The Grill House", businessPhone: "3-7722 9081", businessEmail: "hello@thegrillhouse.my",
    restaurantType: "casual_restaurant", address: "40, Jalan SS 21/39", postcode: "47400", area: "SS 21 (Damansara Uptown, Damansara Utama)", location: { latitude: 3.1335, longitude: 101.6240 },
    ssmNumber: "201901033456", halalStatus: "not_halal", sellsPork: "yes", servesAlcohol: "yes",
    cuisines: ["Western"], averageSpend: "55", facilities: ["Dine-in", "Dinner", "Beer", "Wine", "Credit Card"],
  }),
  submission({
    id: "SUB-1033", submittedAt: ago(20), status: "approved", decidedAt: ago(17), decidedBy: "Daniel Lim",
    managerName: "Farah Nadia", managerPhone: "19-447 1120",
    businessName: "Sweet Tooth Desserts", businessPhone: "19-447 1120", businessEmail: "sweettooth.pj@gmail.com",
    restaurantType: "dessert_shop", address: "8, Jalan PJU 5/9", postcode: "47810", area: "PJU 5 (Kota Damansara, Sierra Damansara, Taman Sains Selangor 1, Villa Damansara)", location: { latitude: 3.1500, longitude: 101.5930 },
    ssmNumber: "202101077120", halalStatus: "halal_certified", halalCertificate: pdf("halal-sweettooth.pdf", 430), halalExpiry: "2027-02-14",
    cuisines: ["Desserts"], averageSpend: "16", facilities: ["Dine-in", "Takeout", "Dessert"],
  }),
  submission({
    id: "SUB-1034", submittedAt: ago(25), status: "approved", decidedAt: ago(22), decidedBy: MOCK_REVIEWER,
    managerName: "Lee Kah Hoe", managerPhone: "12-118 9093",
    businessName: "Restoran Hock Kee", businessPhone: "3-7874 3301", businessEmail: "hockkee.pj@gmail.com",
    restaurantType: "casual_restaurant", address: "18, Jalan SS 2/10", postcode: "47300", area: "SS 2", location: { latitude: 3.1180, longitude: 101.6190 },
    ssmNumber: "199801004321", halalStatus: "not_halal", sellsPork: "yes", servesAlcohol: "yes",
    cuisines: ["Chinese (Malaysia)", "Seafood"], averageSpend: "40", facilities: ["Dine-in", "Dinner", "Beer", "Good for Groups"],
  }),
  submission({
    id: "SUB-1035", submittedAt: ago(40), status: "approved", decidedAt: ago(37), decidedBy: "Daniel Lim",
    managerName: "Priya Nair", managerPhone: "16-990 2234",
    businessName: "Spice Route", businessPhone: "3-7932 5512", businessEmail: "spiceroute.pj@gmail.com",
    restaurantType: "casual_restaurant", address: "5, Jalan 52/1", postcode: "46200", area: "Seksyen 52 (PJ State)", location: { latitude: 3.0975, longitude: 101.6440 },
    ssmNumber: "202001011876", halalStatus: "halal_not_certified",
    cuisines: ["Indian"], averageSpend: "22", facilities: ["Dine-in", "Takeout", "Lunch", "Dinner"],
  }),

  submission({
    id: "SUB-1036", submittedAt: ago(10), status: "rejected", decidedAt: ago(8), decidedBy: MOCK_REVIEWER,
    managerName: "Ahmad Zaki", managerPhone: "11-3300 1122",
    businessName: "Burger Bros PJ", businessPhone: "11-3300 1122", businessEmail: "burgerbros@gmail.com",
    restaurantType: "fast_food", address: "1, Jalan Tiada", postcode: "47300", area: "SS 2", location: { latitude: 3.1189, longitude: 101.6187 },
    ssmNumber: "000000000000", cuisines: ["Burgers"], averageSpend: "20", facilities: ["Takeout"],
    review: {
      ssmNumber: { state: "flagged", note: "This SSM number doesn't exist in the SSM registry." },
      address: { state: "flagged", note: "We couldn't find this address in SS 2." },
    },
  }),
  submission({
    id: "SUB-1037", submittedAt: ago(18), status: "rejected", decidedAt: ago(15), decidedBy: "Daniel Lim",
    managerName: "Lim Siew Ling", managerPhone: "12-441 7789",
    businessName: "Kopi Tiam Lama (SS 2)", businessPhone: "12-441 7789", businessEmail: "ktl.ss2@gmail.com",
    restaurantType: "kopitiam", address: "6, Jalan SS 2/55", postcode: "47300", area: "SS 2", location: { latitude: 3.1201, longitude: 101.6205 },
    ssmNumber: "201501012233", cuisines: ["Chinese (Malaysia)"], averageSpend: "11", facilities: ["Dine-in"],
    review: { businessName: { state: "flagged", note: "This business is already on FoodSight." } },
  }),
  submission({
    id: "SUB-1038", submittedAt: ago(28), status: "rejected", decidedAt: ago(26), decidedBy: MOCK_REVIEWER,
    managerName: "Kevin Ooi", managerPhone: "17-882 0011",
    businessName: "Cloud Bites", businessPhone: "17-882 0011", businessEmail: "cloudbites@gmail.com",
    restaurantType: "cloud_kitchen", address: "33, Jalan PJU 1/3", postcode: "47301", area: "PJU 1 (Taman Bukit Mayang Mas)", location: { latitude: 3.1050, longitude: 101.6000 },
    ssmNumber: "202401055501", serviceStyle: "delivery_only", cuisines: ["Fusion"], averageSpend: "25", facilities: ["Delivery"],
    review: { premisesLicence: { state: "flagged", note: "The licence belongs to a different company." } },
  }),
];
