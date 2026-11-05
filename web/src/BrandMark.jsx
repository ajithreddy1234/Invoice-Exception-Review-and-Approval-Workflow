import React from "react";
import invoiceMark from "./assets/invoice-mark.svg";

export default function BrandMark() {
  return <span className="brand-mark" aria-hidden="true"><img src={invoiceMark} alt="" /></span>;
}
