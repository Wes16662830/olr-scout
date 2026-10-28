/* SYNTHETIC fixture bundle: the real endpoint name is unknown; this tests discovery logic only */
const A=e=>fetch(`/api/auctions/${e}/lots`);const B=e=>s.get("/api/lots?auctionId="+e);const C=e=>s.get(`/api/auction-lots/by-auction/${e}`);
