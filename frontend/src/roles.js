// Where an account belongs: admins (auth.users.is_superuser) on the admin pages, everyone else
// in the chat. Used by the route guards and after login.
export const homeFor = (user) => (user?.is_superuser ? "/admin" : "/chat");
