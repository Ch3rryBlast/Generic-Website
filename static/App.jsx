import { BrowserRouter, Routes, Route } from "react-router-dom";
import Navbar from "./components/NavBar";
import Home from "./pages/Home";
import Dashboard from "./pages/Dashboard";
import Recycle from "./pages/Recycle";
import Exchange from "./pages/Exchange";
import PostItem from "./pages/PostItem";

function App() {
  return (
    <BrowserRouter>
      <Navbar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/recycle" element={<Recycle />} />
        <Route path="/exchange" element={<Exchange />} />
        <Route path="/post" element={<PostItem />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;