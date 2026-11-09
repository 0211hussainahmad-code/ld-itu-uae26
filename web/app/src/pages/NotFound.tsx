import { useEffect } from "react";
import { Link } from "react-router";
import { BrokenLink } from "../components/StateViews";
import s from "../components/StateViews.module.css";
import { TITLES } from "../lib/wording";

export function NotFound() {
  useEffect(() => { document.title = TITLES["404"]!; }, []);
  return (
    <section className={`${s.wrap} ${s.refused}`}>
      <BrokenLink />
      <p className={s.status} data-kind="not-found">404</p>
      <h1 className={s.title}>This link is down</h1>
      <p className={s.text}>There is no page at this address. The story, the replay and the record are one step away.</p>
      <p className={s.exits}><Link to="/" className="btn btn-primary">Back to the story</Link><Link to="/walkthrough" className="btn">Judge walkthrough</Link><Link to="/replay" className="btn">Open the replay</Link></p>
    </section>
  );
}
