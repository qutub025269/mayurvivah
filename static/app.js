// Mayur Vivah - storefront/admin enhancements
document.addEventListener("DOMContentLoaded", function () {
  // Mobile nav toggle
  var toggle = document.querySelector(".menu-toggle");
  var header = document.querySelector(".site-header");
  if (toggle && header) {
    toggle.addEventListener("click", function () {
      header.classList.toggle("nav-open");
    });
  }

  // Product card hover swap
  document.querySelectorAll(".card-img[data-hover-images]").forEach(function (card) {
    try {
      var images = JSON.parse(card.getAttribute("data-hover-images") || "[]");
      if (images.length > 1) {
        var mainImg = card.querySelector(".card-main-image");
        var hoverImg = card.querySelector(".card-hover-image");
        if (mainImg && hoverImg) {
          card.addEventListener("mouseenter", function () {
            hoverImg.src = hoverImg.src || "";
            var altSrc = images[1] || images[0];
            hoverImg.src = card.dataset.basePath ? card.dataset.basePath + altSrc : "/static/" + altSrc;
          });
          card.addEventListener("mouseleave", function () {
            hoverImg.src = "";
          });
        }
      }
    } catch (err) {
      // ignore invalid JSON
    }
  });

  // Product gallery: switch thumbnails and open the main image in a focused zoom view.
  var mainProductImage = document.getElementById("product-main-image");
  var zoomArea = document.getElementById("product-zoom-area");
  document.querySelectorAll(".detail-thumbnail").forEach(function (thumbnail) {
    thumbnail.addEventListener("click", function () {
      if (!mainProductImage) return;
      mainProductImage.src = thumbnail.dataset.galleryImage;
      document.querySelectorAll(".detail-thumbnail").forEach(function (item) { item.classList.remove("active"); });
      thumbnail.classList.add("active");
    });
  });
  if (zoomArea && mainProductImage) {
    var openZoom = function () {
      zoomArea.classList.toggle("zoomed");
    };
    zoomArea.addEventListener("click", openZoom);
    zoomArea.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openZoom(); }
    });
  }

  // Quick View modal
  var quickButtons = document.querySelectorAll(".quick-view-btn");
  quickButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      var modal = document.getElementById("quick-view-modal");
      if (!modal) return;

      var title = button.dataset.productName || "Product";
      var price = button.dataset.productPrice || "";
      var image = button.dataset.productImage || "";
      var stock = button.dataset.productStock || "0";
      var link = button.dataset.productLink || "/";

      document.getElementById("quick-view-title").textContent = title;
      document.getElementById("quick-view-price").textContent = price;
      document.getElementById("quick-view-image").src = image;
      document.getElementById("quick-view-stock").textContent = stock > 0 ? stock + " left in stock" : "Out of stock";
      document.getElementById("quick-view-link").href = link;

      modal.classList.add("open");
    });
  });

  var quickClose = document.getElementById("quick-view-close");
  if (quickClose) {
    quickClose.addEventListener("click", function () {
      document.getElementById("quick-view-modal").classList.remove("open");
    });
  }

  var modal = document.getElementById("quick-view-modal");
  if (modal) {
    modal.addEventListener("click", function (event) {
      if (event.target === modal) {
        modal.classList.remove("open");
      }
    });
  }

  // Live preview for admin product image upload
  var input = document.getElementById("img-input");
  var preview = document.getElementById("new-preview");
  if (input && preview) {
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) {
        alert("Image must be smaller than 5 MB.");
        input.value = "";
        return;
      }
      var reader = new FileReader();
      reader.onload = function (e) {
        preview.src = e.target.result;
        preview.classList.remove("hidden");
      };
      reader.readAsDataURL(file);
    });
  }
});
