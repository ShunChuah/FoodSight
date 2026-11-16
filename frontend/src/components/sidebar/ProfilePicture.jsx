import { useState } from "react";
import avatar from "../../assets/avatar.svg";
import { useAuth } from "../../context/AuthContext.jsx";

// No picture, or one that fails to load, shows the default avatar. referrerPolicy:
// Google's image server can refuse a request that says which page it came from.
export function Picture({ url, className }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return <img className={`${className} default-avatar`} src={avatar} alt="Profile" />;
  }
  return (
    <img
      className={className}
      src={url}
      alt="Profile"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

// The logged-in user's picture (auth.users.profile_picture_url), the same one the top bar shows.
function ProfilePicture({ className }) {
  const { user } = useAuth();
  const url = user?.profile_picture_url;
  return <Picture key={url || "default"} url={url} className={className} />;
}

export default ProfilePicture;
